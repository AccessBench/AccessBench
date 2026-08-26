# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Run a live AccessBench subject model against paired enforcers.

The raw JSONL is checkpointed once per episode. A sidecar manifest binds the
catalog, scenario and oracle versions, sample, decoding settings, code state,
and expected episode matrix before inference begins.

The public interface has exactly two benchmark inputs:

    python3 eval/run_eval.py --model Qwen/Qwen3-32B \
        --enforcement label_governance

Transport configuration comes from the environment. The panel, decoding
settings, oracle, and output location are fixed protocol machinery.

The protocol runs each case once per arm. `--repeats` raises that for a
stability profile; it is a diagnostic setting, not a benchmark input, and a
run with repeats above one is not the reportable protocol configuration.
"""

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
LAB_ROOT = os.path.dirname(HERE)
sys.path.insert(0, LAB_ROOT)

from accessbench_env import oracle
from accessbench_env.agent_runner import (
    SubjectAgent,
    is_transport_failure,
    run_agent_trial,
)
from accessbench_env.blueprints import BLUEPRINT_BY_ID
from accessbench_env.enforcers import build_enforcer, built_in_identity
from accessbench_env.evidence import (
    chain_record,
    load_signing_key,
    sign_attestation,
    verify_record_chain,
)
from accessbench_env.panel import (
    CORE_PANEL_ID,
    CORE_PANEL_STATUS,
    SEALED_PANEL_ADMITTED_STATUS,
    SEALED_PANEL_CANDIDATE_STATUS,
    SEALED_PANEL_ID,
    build_core_panel,
    core_panel_manifest,
)
from accessbench_env.sealed_assets import (
    AwsKmsProvider,
    SealedCatalogReader,
    inspect_sealed,
    read_sealed_catalog_index,
)


REFERENCE_ONLY_OPERATIONS = frozenset({"inference", "retention", "covert"})
# One pass over the fixed bank per arm. Measured on five paired 600-case runs
# (2026-08-19, gpt-4o, gpt-5.4, gpt-5.6-sol): a single pass reproduced the
# three-pass exfiltration rate to within 0.32 points and the three-pass task
# rates to within 1.2 points, against arm gaps of 13 to 43 points. Exact-match
# exfiltration, the headline, disagreed across passes on 0 to 4 of 600 cases.
# Repetition bought precision two orders of magnitude finer than the effect and
# cost three times the money. See docs/02-methodology.md section 12.
PROTOCOL_K = 1
PROTOCOL_TEMPERATURE = 0.0
PROTOCOL_CONCURRENCY = 16
PROTOCOL_MAX_TURNS = 8
PROTOCOL_SEED = 7
PROTOCOL_PARALLEL_TOOL_CALLS = False
MANIFEST_SCHEMA_VERSION = "accessbench-live-run-v4"
EPISODE_ATTEMPTS = 3          # transport machinery, not a benchmark input
EPISODE_BACKOFF_S = (3.0, 12.0)
TRANSPORT_ABORT_STREAK = 10   # consecutive operator failures that abort the run


def _default_output_path(model: str) -> Path:
    slug = "".join(
        character.lower() if character.isalnum() else "-"
        for character in model
    ).strip("-")[:48] or "model"
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(LAB_ROOT) / "results_raw" / f"{timestamp}-{slug}.jsonl"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _stable_hex(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _matches_cell(trial: dict, variant: str, profile: str) -> bool:
    return (
        trial.get("flow_variant") == variant
        and trial.get("enterprise_profile_id") == profile
    )


def _target_cells(rows: list[dict]) -> tuple[tuple[str, str], ...]:
    """Cover each relevant posture and sample every polarity twice.

    A workflow is paired only with the strict posture that makes its documented
    policy coordinate change outcome. Requiring unrelated profiles would invent
    false policy flips for coordinates those profiles do not enforce.
    """
    profiles = sorted({row["enterprise_profile_id"] for row in rows})
    if "collaboration_open" not in profiles or len(profiles) < 2:
        raise ValueError("sample requires open and at least one strict posture")
    strict = [profile for profile in profiles if profile != "collaboration_open"]
    first = strict[0]
    middle = strict[1] if len(strict) > 1 else first
    last = strict[-1]
    return (
        ("common_allow", "collaboration_open"),
        ("common_allow", first),
        ("posture_sensitive", "collaboration_open"),
        ("posture_sensitive", middle),
        ("common_deny", last),
        ("common_deny", first),
    )


def _choose_covering(
    candidates: list[dict],
    chosen: list[dict],
    seed: int,
    mechanism: str,
    cell: object,
) -> dict:
    used_blueprints = {t["blueprint_id"] for t in chosen}
    used_carriers = {t["carrier_style"] for t in chosen}
    used_surfaces = {t["surface"] for t in chosen}
    used_labels = {t["label_regime"] for t in chosen}

    def rank(trial: dict) -> tuple:
        return (
            trial["blueprint_id"] in used_blueprints,
            trial["carrier_style"] in used_carriers,
            trial["surface"] in used_surfaces,
            trial["label_regime"] in used_labels,
            _stable_hex(seed, mechanism, cell, trial["trial_id"]),
        )

    return min(candidates, key=rank)


def stratified_trials(
    catalog: str,
    per_mechanism: int,
    seed: int,
    *,
    include_reference_only: bool = False,
) -> list[dict]:
    """Select a deterministic covering sample for every supported mechanism.

    Eight trials are the minimum. They cover every mechanism-relevant posture,
    include at least two trials from each triad polarity, and span at least two
    workflow blueprints and every prompt surface. The stable hash makes
    different seeds select different grounded trials.
    """
    if per_mechanism < 8:
        raise ValueError("per_mechanism must be at least 8 for coverage")
    with open(catalog, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return stratified_trial_rows(
        rows,
        per_mechanism,
        seed,
        include_reference_only=include_reference_only,
    )


def stratified_trial_rows(
    catalog_rows: list[dict],
    per_mechanism: int,
    seed: int,
    *,
    include_reference_only: bool = False,
) -> list[dict]:
    """Select a covering sample from already authenticated catalog rows."""
    if per_mechanism < 8:
        raise ValueError("per_mechanism must be at least 8 for coverage")
    by_mechanism: dict[str, list[dict]] = {}
    for trial in catalog_rows:
        operation = BLUEPRINT_BY_ID[trial["blueprint_id"]].operation
        if operation in REFERENCE_ONLY_OPERATIONS and not include_reference_only:
            continue
        by_mechanism.setdefault(trial["mechanism"], []).append(trial)

    picked: list[dict] = []
    for mechanism in sorted(by_mechanism):
        rows = by_mechanism[mechanism]
        chosen: list[dict] = []
        for variant, profile in _target_cells(rows):
            if len(chosen) >= per_mechanism:
                break
            candidates = [
                trial for trial in rows
                if trial not in chosen and _matches_cell(trial, variant, profile)
            ]
            if not candidates:
                raise ValueError(
                    f"{mechanism}: no candidate for {variant}/{profile}"
                )
            chosen.append(_choose_covering(
                candidates, chosen, seed, mechanism, (variant, profile)
            ))
        while len(chosen) < per_mechanism:
            candidates = [trial for trial in rows if trial not in chosen]
            if not candidates:
                break
            chosen.append(_choose_covering(
                candidates, chosen, seed, mechanism, f"fill-{len(chosen)}"
            ))
        if len({trial["blueprint_id"] for trial in chosen}) < 2:
            raise ValueError(f"{mechanism}: sample does not span two workflows")
        covered_surfaces = {trial["surface"] for trial in chosen}
        available_surfaces = {trial["surface"] for trial in rows}
        if covered_surfaces != available_surfaces:
            raise ValueError(
                f"{mechanism}: sample does not cover every prompt surface"
            )
        polarity_counts = Counter(trial["flow_variant"] for trial in chosen)
        if any(polarity_counts[variant] < 2 for variant in (
            "common_allow", "posture_sensitive", "common_deny"
        )):
            raise ValueError(f"{mechanism}: sample has fewer than two trials per polarity")
        covered_postures = {
            trial["enterprise_profile_id"] for trial in chosen
        }
        available_postures = {
            trial["enterprise_profile_id"] for trial in rows
        }
        if covered_postures != available_postures:
            raise ValueError(
                f"{mechanism}: sample does not cover every relevant posture"
            )
        picked.extend(chosen)
    return picked


def _git_state() -> dict:
    repo = str(Path(LAB_ROOT).parent)

    def run(*args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    source = "repository"
    if commit is None:
        commit = os.environ.get("ACCESSBENCH_HARNESS_GIT_COMMIT") or None
        asserted_dirty = os.environ.get("ACCESSBENCH_HARNESS_GIT_DIRTY")
        status = None if asserted_dirty is None else (
            "asserted-dirty" if asserted_dirty.lower() in {"1", "true", "yes"} else ""
        )
        source = "operator_assertion" if commit else "unavailable"
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "source": source,
    }


def _runtime_code_state() -> dict:
    paths = sorted(Path(LAB_ROOT, "accessbench_env").glob("*.py"))
    paths.append(Path(__file__).resolve())
    files = {
        str(path.relative_to(LAB_ROOT)): _sha256_file(path)
        for path in paths
    }
    commitment = hashlib.sha256(json.dumps(
        files, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {"commitment": commitment, "files": files}


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _episode_key(record: dict) -> tuple[str, str, int]:
    reference_id = record.get("sealed_record_id") or record["trial_id"]
    return record["enforcer"], reference_id, int(record["repeat"])


def _trial_reference_id(trial_reference: dict) -> str:
    reference_id = (
        trial_reference.get("record_id") or trial_reference.get("trial_id")
    )
    if not reference_id:
        raise ValueError("episode task lacks a public or opaque reference ID")
    return str(reference_id)


def _task_episode_key(task: tuple[str, dict, int]) -> tuple[str, str, int]:
    enforcer, trial_reference, repeat = task
    return enforcer, _trial_reference_id(trial_reference), int(repeat)


def _failure_evidence(exc: BaseException) -> dict:
    """Non-secret transport evidence for one exhausted episode."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, str) and status_code.isdecimal():
        status_code = int(status_code)
    if (
        not isinstance(status_code, int)
        or isinstance(status_code, bool)
        or not 100 <= status_code <= 599
    ):
        status_code = None
    provider_code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    if provider_code is None and isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            provider_code = error.get("code")
    provider_code_sha256 = None
    if isinstance(provider_code, (int, str)) and not isinstance(
        provider_code, bool
    ):
        provider_code_sha256 = hashlib.sha256(
            str(provider_code).encode("utf-8")
        ).hexdigest()
    return {
        "exception_type": type(exc).__name__,
        "status_code": status_code,
        "provider_code_sha256": provider_code_sha256,
        "message_sha256": hashlib.sha256(str(exc).encode("utf-8")).hexdigest(),
    }


def _request_seed(seed: int, trial_id: str, repeat: int) -> int:
    return int(_stable_hex(seed, trial_id, repeat)[:8], 16) % (2**31)


def _paired_episode_tasks(
    enforcers: list[str], trials: list[dict], repeat_k: int
) -> list[tuple[str, dict, int]]:
    """Pair arms while separating repeats across shuffled full-panel passes."""
    tasks = []
    prior_reference_id = None
    for repeat in range(repeat_k):
        ordered_trials = sorted(
            trials,
            key=lambda trial: _stable_hex(
                "block-order",
                PROTOCOL_SEED,
                repeat,
                _trial_reference_id(trial),
            ),
        )
        if ordered_trials:
            first_reference_id = _trial_reference_id(ordered_trials[0])
            if first_reference_id == prior_reference_id and len(ordered_trials) > 1:
                ordered_trials = ordered_trials[1:] + ordered_trials[:1]
        for trial in ordered_trials:
            reference_id = _trial_reference_id(trial)
            offset = int(
                _stable_hex("arm-order", reference_id, repeat)[:8], 16
            ) % len(enforcers)
            ordered = enforcers[offset:] + enforcers[:offset]
            tasks.extend((enforcer, trial, repeat) for enforcer in ordered)
            prior_reference_id = reference_id
    return tasks



def _is_local_endpoint(base_url: str) -> bool:
    """True for endpoints that do not bill per call: localhost and private nets."""
    from urllib.parse import urlparse
    host = (urlparse(base_url).hostname or "").lower()
    return (
        host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        or host.startswith(("10.", "192.168."))
        or any(host.startswith(f"172.{n}.") for n in range(16, 32))
        or host.endswith((".local", ".internal", ".lan"))
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one model against one enforcement layer and the fixed no-"
            "enforcement baseline. All other benchmark settings are fixed."
        ),
    )
    parser.add_argument("--model", required=True, help="subject model ID")
    parser.add_argument(
        "--enforcement",
        required=True,
        help="built-in enforcement ID or an AuthZEN server URL",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=PROTOCOL_K,
        help=(
            "diagnostic only: passes over the bank per arm. The protocol is 1. "
            "Values above 1 measure case-level flakiness and multiply cost by "
            "the same factor; they are not the reportable configuration."
        ),
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    repeat_k = args.repeats
    model_revision = os.environ.get("ACCESSBENCH_MODEL_REVISION", "")
    model_weight_revision = os.environ.get(
        "ACCESSBENCH_MODEL_WEIGHT_REVISION", ""
    )
    quant = os.environ.get("ACCESSBENCH_MODEL_QUANTIZATION", "")
    model_server = {
        "software": os.environ.get("ACCESSBENCH_MODEL_SERVER_SOFTWARE", ""),
        "version": os.environ.get("ACCESSBENCH_MODEL_SERVER_VERSION", ""),
        "serve_config_sha256": os.environ.get(
            "ACCESSBENCH_MODEL_SERVER_CONFIG_SHA256", ""
        ),
        "preflight_sha256": os.environ.get(
            "ACCESSBENCH_MODEL_PREFLIGHT_SHA256", ""
        ),
        "orchestrator_sha256": os.environ.get(
            "ACCESSBENCH_MODEL_ORCHESTRATOR_SHA256", ""
        ),
    }
    base_url = os.environ.get(
        "ACCESSBENCH_MODEL_BASE_URL", "http://localhost:8000/v1"
    )
    api_key = os.environ.get("OPENAI_API_KEY", "local-no-key")
    api_mode = os.environ.get("ACCESSBENCH_MODEL_API_MODE", "auto")
    if api_mode not in {"auto", "responses", "chat_completions"}:
        parser.error("ACCESSBENCH_MODEL_API_MODE has an unsupported value")
    resolved_api_mode = api_mode
    if resolved_api_mode == "auto":
        resolved_api_mode = (
            "responses" if "api.openai.com" in base_url
            else "chat_completions"
        )
    # Spend discipline. A hosted endpoint costs money on every episode. No run
    # against one starts unless the operator states the approval explicitly,
    # in this environment variable, for this invocation. Local endpoints
    # (localhost, 127.0.0.1, private addresses) are exempt. Smoke mode still
    # needs approval; it is cheap, not free.
    hosted_base = os.environ.get("ACCESSBENCH_MODEL_BASE_URL", "http://localhost:8000/v1")
    pinned_evidence_track = (
        not _is_local_endpoint(hosted_base)
        or os.environ.get("ACCESSBENCH_REQUIRE_PINNED_LOCAL") == "yes"
    )
    if (
        _is_local_endpoint(hosted_base)
        and os.environ.get("ACCESSBENCH_REQUIRE_PINNED_LOCAL") == "yes"
    ):
        missing = []
        if not model_weight_revision:
            missing.append("ACCESSBENCH_MODEL_WEIGHT_REVISION")
        if not quant:
            missing.append("ACCESSBENCH_MODEL_QUANTIZATION")
        for field, value in model_server.items():
            if not value:
                missing.append(f"model_server.{field}")
        git_probe = _git_state()
        if not git_probe.get("commit") or git_probe.get("dirty") is not False:
            missing.append("clean pinned harness Git commit")
        if missing:
            parser.error(
                "pinned local evidence is incomplete: " + ", ".join(missing)
            )
    if not _is_local_endpoint(hosted_base) and os.environ.get("ACCESSBENCH_SPEND_APPROVED") != "yes":
        parser.error(
            "this run would spend money on a hosted model endpoint. Set "
            "ACCESSBENCH_SPEND_APPROVED=yes only when PJ has approved this specific "
            "run, the harness is not under iteration, and the spend is necessary."
        )
    signing_key_path = os.environ.get("ACCESSBENCH_SIGNING_KEY")
    if not signing_key_path:
        parser.error(
            "ACCESSBENCH_SIGNING_KEY must name the evaluator's Ed25519 private "
            "key; provision one with accessbench-env generate-signing-key"
        )
    signing_key_resolved = Path(signing_key_path).expanduser().resolve()
    result_root_resolved = (Path(LAB_ROOT) / "results_raw").resolve()
    if (
        signing_key_resolved == result_root_resolved
        or result_root_resolved in signing_key_resolved.parents
    ):
        parser.error("ACCESSBENCH_SIGNING_KEY must be outside results_raw")
    signing_key = load_signing_key(signing_key_path)
    if "," in args.enforcement:
        parser.error("--enforcement accepts exactly one enforcement input")
    if args.enforcement == "none":
        parser.error(
            "--enforcement must name the enforced arm; the none baseline is automatic"
        )
    enforcers = ["none", args.enforcement]
    if not enforcers:
        parser.error("--enforcement must not be empty")
    if len(enforcers) != len(set(enforcers)):
        parser.error("enforcement arms must be distinct")

    sealed_provider = None
    smoke_mode = False
    sealed_catalog = os.environ.get("ACCESSBENCH_SEALED_CATALOG")
    if sealed_catalog:
        catalog_path = sealed_catalog
        sealed_metadata = inspect_sealed(catalog_path)
        if sealed_metadata["encryption_context"].get("AssetType") != "heldout-catalog":
            parser.error("--sealed-catalog must be a heldout-catalog asset")
        sealed_provider = AwsKmsProvider(sealed_metadata["region"])
        if sealed_metadata.get("panel_id") != SEALED_PANEL_ID:
            parser.error("sealed catalog does not use the sealed v1 panel identity")
        if sealed_metadata.get("panel_status") not in {
            SEALED_PANEL_CANDIDATE_STATUS,
            SEALED_PANEL_ADMITTED_STATUS,
        }:
            parser.error("sealed catalog lacks a recognized evaluation status")
        if sealed_metadata.get("record_n") != 600:
            parser.error("sealed core panel must contain exactly 600 cases")
        trials = read_sealed_catalog_index(catalog_path)
        catalog_rows = None
        catalog_storage = "aws-kms-sealed"
        scenario_version = sealed_metadata["scenario_version"]
        oracle_version = sealed_metadata["oracle_version"]
        split = sealed_metadata["split"]
        if split != "heldout":
            parser.error("sealed evaluation candidates must use the heldout split")
    else:
        catalog_path = os.path.join(LAB_ROOT, "catalog", "core_v2.jsonl")
        with open(catalog_path, encoding="utf-8") as handle:
            catalog_rows = [
                json.loads(line) for line in handle if line.strip()
            ]
        trials = build_core_panel(catalog_rows)
        catalog_storage = "plaintext"
        smoke_trials = os.environ.get("ACCESSBENCH_SMOKE_TRIALS", "").strip()
        if smoke_trials:
            # Development-only smoke: a handful of cases to measure cost and
            # latency before a full run. Never eligible for anything; the
            # manifest says so and aggregation treats non-core as diagnostic.
            smoke_n = int(smoke_trials)
            if smoke_n < 1 or smoke_n > len(trials):
                parser.error("ACCESSBENCH_SMOKE_TRIALS must be between 1 and the panel size")
            trials = trials[:smoke_n]
            smoke_mode = True
        versions = {
            (t["scenario_version"], t["oracle_version"]) for t in trials
        }
        if len(versions) != 1:
            raise SystemExit(f"sample spans scenario or oracle versions: {versions}")
        scenario_version, oracle_version = next(iter(versions))
        splits = {t["split"] for t in trials}
        if len(splits) != 1:
            raise SystemExit(f"sample spans catalog splits: {splits}")
        split = next(iter(splits))
    selected_mechanisms = sorted({
        blueprint.mechanism for blueprint in BLUEPRINT_BY_ID.values()
        if blueprint.operation not in REFERENCE_ONLY_OPERATIONS
    }) if sealed_catalog else sorted({t["mechanism"] for t in trials})
    catalog_operations = {
        blueprint.operation for blueprint in BLUEPRINT_BY_ID.values()
    }
    selected_operations = {
        blueprint.operation for blueprint in BLUEPRINT_BY_ID.values()
        if blueprint.operation not in REFERENCE_ONLY_OPERATIONS
    } if sealed_catalog else {
        BLUEPRINT_BY_ID[trial["blueprint_id"]].operation for trial in trials
    }
    reference_only_mechanisms = sorted({
        blueprint.mechanism for blueprint in BLUEPRINT_BY_ID.values()
        if blueprint.operation in REFERENCE_ONLY_OPERATIONS
    })
    catalog_sha = _sha256_file(catalog_path)
    output = _default_output_path(args.model)
    if smoke_mode:
        output = output.with_name(output.stem + "-smoke" + output.suffix)
    if split == "heldout":
        private_output_root = (Path(LAB_ROOT) / "results_raw").resolve()
        resolved_output = output.resolve()
        if private_output_root not in resolved_output.parents:
            parser.error(
                "heldout raw evidence must be written under the ignored "
                "environment_lab/results_raw directory"
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(str(output) + ".manifest.json")

    panel = (
        {
            "trial_ids_sha256": None,
            "sealed_index_sha256": sealed_metadata["index_sha256"],
        }
        if sealed_catalog else core_panel_manifest(catalog_rows)
    )
    active_panel_id = (
        sealed_metadata["panel_id"] if sealed_catalog else CORE_PANEL_ID
    )
    active_panel_status = (
        sealed_metadata["panel_status"] if sealed_catalog else CORE_PANEL_STATUS
    )
    config = {
        "benchmark_inputs": {
            "model": args.model,
            "enforcement": args.enforcement,
        },
        "model": args.model,
        "model_revision": model_revision,
        "model_weight_revision": model_weight_revision,
        "quant": quant,
        "model_server": model_server,
        "client_software": {"openai": _package_version("openai")},
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "evidence_track": "pinned-trial-v1" if pinned_evidence_track else "diagnostic",
        "base_url": base_url,
        "api_mode": api_mode,
        "resolved_api_mode": resolved_api_mode,
        "enforcers": enforcers,
        "k_repeats": repeat_k,
        "evaluation_mode": "smoke" if smoke_mode else "core",
        "panel_id": active_panel_id,
        "panel_status": active_panel_status,
        "panel_trial_ids_sha256": panel["trial_ids_sha256"],
        "sealed_index_sha256": panel.get("sealed_index_sha256"),
        "bank_complete": not smoke_mode,
        "per_mechanism": (
            max(Counter(t["mechanism"] for t in trials).values())
            if smoke_mode else 24
        ),
        "temperature": PROTOCOL_TEMPERATURE,
        "temperature_semantics": (
            "protocol target; exact provider request is signed in "
            "observed_decoding_requests"
        ),
        "concurrency": PROTOCOL_CONCURRENCY,
        "max_turns": PROTOCOL_MAX_TURNS,
        "enable_thinking": False,
        "reasoning_effort": None,
        "parallel_tool_calls": PROTOCOL_PARALLEL_TOOL_CALLS,
        "sample_seed": None,
        "decoding": {
            "temperature": PROTOCOL_TEMPERATURE,
            "protocol_seed": PROTOCOL_SEED,
            "request_seed_derivation": "sha256(protocol_seed,trial_id,repeat)-31bit",
            "provider_seed_policy": (
                "sent-when-endpoint-supports-seed"
                if resolved_api_mode != "responses"
                else "not-supported-by-openai-responses"
            ),
            "thinking_requested": False,
            "reasoning_effort": None,
            "parallel_tool_calls": PROTOCOL_PARALLEL_TOOL_CALLS,
            "tool_call_protocol": "exactly-one-per-assistant-turn",
        },
        "built_in_enforcement_identities": [
            built_in_identity(name) for name in enforcers
            if built_in_identity(name) is not None
        ],
        "catalog_sha256": catalog_sha,
        "catalog_storage": catalog_storage,
        "scenario_version": scenario_version,
        "oracle_version": oracle_version,
        "split": split,
        "include_reference_only": False,
        "trial_ids": [t["trial_id"] for t in trials] if not sealed_catalog else [],
        "sealed_record_ids": (
            [t["record_id"] for t in trials] if sealed_catalog else []
        ),
    }
    config_commitment = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    code_state = _runtime_code_state()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "transport": {
            "model_max_retries": int(os.environ.get("ACCESSBENCH_MODEL_MAX_RETRIES", "6")),
            "model_timeout_s": float(os.environ.get("ACCESSBENCH_MODEL_TIMEOUT_S", "180")),
            "episode_attempts": EPISODE_ATTEMPTS,
            "exhausted_episode_attempts": [],
        },
        "status": "running",
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_commitment": config_commitment,
        "config": config,
        "python": sys.version,
        "platform": platform.platform(),
        "git": _git_state(),
        "runtime_code": code_state,
        "selected_mechanisms": selected_mechanisms,
        "reference_only_operations": sorted(REFERENCE_ONLY_OPERATIONS),
        "reference_only_mechanisms": reference_only_mechanisms,
        "operations_present": sorted(selected_operations),
        "catalog_operations": sorted(catalog_operations),
        "expected_episode_n": len(enforcers) * len(trials) * repeat_k,
    }
    pre_run_attestation_payload = {
        "schema_version": manifest["schema_version"],
        "started_at": manifest["started_at"],
        "config_commitment": manifest["config_commitment"],
        "runtime_code_commitment": manifest["runtime_code"]["commitment"],
        "git": manifest["git"],
        "expected_episode_n": manifest["expected_episode_n"],
    }
    manifest["pre_run_attestation_payload"] = pre_run_attestation_payload
    manifest["pre_run_attestation"] = sign_attestation(
        pre_run_attestation_payload,
        signing_key,
        purpose="accessbench-pre-run-v1",
    )

    existing: list[dict] = []
    resume_raw = os.environ.get("ACCESSBENCH_RESUME_RAW", "").strip()
    if resume_raw:
        # Continue an interrupted run. The prior manifest must bind the same
        # configuration; the retained records must form a valid chain. The
        # chain continues from its head. Records already present are never
        # re-run, so a resumed run cannot double-count an episode.
        resume_path = Path(resume_raw).expanduser().resolve()
        resume_manifest_path = Path(str(resume_path) + ".manifest.json")
        if not resume_path.exists() or not resume_manifest_path.exists():
            raise SystemExit("ACCESSBENCH_RESUME_RAW needs an existing raw file and manifest")
        prior = json.loads(resume_manifest_path.read_text(encoding="utf-8"))
        if prior.get("config_commitment") != config_commitment:
            raise SystemExit(
                "resume refused: prior manifest binds a different configuration "
                "(model, enforcement, catalog, protocol, or panel differ)"
            )
        if prior.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise SystemExit(
                "resume refused: prior manifest was written under schema "
                f"{prior.get('schema_version')!r}, this runner writes "
                f"{MANIFEST_SCHEMA_VERSION!r}; start a fresh run"
            )
        if prior.get("status") == "complete":
            raise SystemExit("resume refused: prior run is already complete")
        existing = [
            json.loads(line)
            for line in resume_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        resumed_head = verify_record_chain(existing)
        output = resume_path
        manifest_path = resume_manifest_path
        manifest = prior
        manifest["status"] = "running"
        for field in (
            "finished_at", "completed_episode_n", "error_episode_n",
            "duplicate_episode_key_n", "raw_sha256",
            "raw_chain_head_sha256", "observed_response_models",
            "response_metadata_complete", "provider_response_ids_unique",
            "client_episode_sessions_unique", "observed_system_fingerprints",
            "observed_decoding_requests", "observed_enforcement_identities",
            "enforcement_identity_complete",
            "enforcement_session_isolation_observed", "unresolved_episode_n",
            "unresolved_episode_keys", "unresolved_episode_keys_sha256",
            "unexpected_episode_n", "exhausted_episode_attempt_n",
            "exhausted_episode_attempts_sha256", "result_attestation_payload",
            "result_attestation",
        ):
            manifest.pop(field, None)
        manifest.setdefault("transport", {}).setdefault(
            "exhausted_episode_attempts", []
        )
        manifest["transport"].pop("abort", None)
        manifest.setdefault("resumed_at", []).append(
            dt.datetime.now(dt.timezone.utc).isoformat()
        )
        _write_manifest(manifest_path, manifest)
        print(f"resuming {resume_path.name}: {len(existing)} episodes retained", flush=True)
    elif output.exists() or manifest_path.exists():
        raise SystemExit("generated output collision; run again")
    else:
        output.open("x", encoding="utf-8").close()
        _write_manifest(manifest_path, manifest)

    print(f"RAW_PATH={output}", flush=True)

    completed_keys = {_episode_key(record) for record in existing}
    all_tasks = _paired_episode_tasks(enforcers, trials, repeat_k)
    tasks = [task for task in all_tasks if _task_episode_key(task) not in completed_keys]
    sealed_reader = (
        SealedCatalogReader(catalog_path, provider=sealed_provider)
        if sealed_provider is not None else None
    )
    lock = threading.Lock()
    # Circuit breaker. A billing stop, a revoked key, or a dead network is an
    # operator failure, not model behavior. After a streak of them the run
    # aborts and writes nothing for the affected episodes, so the raw stays
    # clean and a later resume re-runs exactly what is missing.
    breaker = {"streak": 0, "tripped": False, "reason": "", "skipped": 0}
    done = {"n": len(existing)}
    chain_state = {"previous": verify_record_chain(existing) if existing else None}
    scheduled_n = len(tasks)
    print(
        f"model={args.model} enforcers={enforcers} trials={len(trials)} "
        f"mechanisms={len(selected_mechanisms)} k={repeat_k} -> "
        f"{len(all_tasks)} expected, {scheduled_n} scheduled, "
        f"concurrency={PROTOCOL_CONCURRENCY}, temp={PROTOCOL_TEMPERATURE}",
        flush=True,
    )
    if reference_only_mechanisms:
        print(
            "reference-only mechanisms excluded from the live headline: "
            + ",".join(reference_only_mechanisms),
            flush=True,
        )

    def one(task: tuple[str, dict, int]) -> dict | None:
        enforcer_name, trial_reference, repeat = task
        with lock:
            if breaker["tripped"]:
                breaker["skipped"] += 1
                return None
        trial = (
            sealed_reader.read_entry(trial_reference)
            if sealed_reader is not None else trial_reference
        )
        enforcer = build_enforcer(enforcer_name)
        operation = BLUEPRINT_BY_ID[trial["blueprint_id"]].operation
        request_seed = _request_seed(PROTOCOL_SEED, trial["trial_id"], repeat)
        shared = {
            "model": args.model,
            "model_revision": model_revision,
            "model_weight_revision": model_weight_revision,
            "quant": quant,
            "enforcer": enforcer_name,
            "repeat": repeat,
            "request_seed": request_seed,
            "trial_id": trial["trial_id"],
            "blueprint_id": trial["blueprint_id"],
            "mechanism": trial["mechanism"],
            "operation": operation,
            "live_support": (
                "reference_only" if operation in REFERENCE_ONLY_OPERATIONS
                else "supported"
            ),
            "flow_variant": trial.get("flow_variant"),
            "enterprise_profile_id": trial.get("enterprise_profile_id"),
            "surface": trial.get("surface"),
            "carrier_style": trial.get("carrier_style"),
            "label_regime": trial.get("label_regime"),
            "scenario_version": trial["scenario_version"],
            "oracle_version": trial["oracle_version"],
            "catalog_sha256": catalog_sha,
            "split": trial["split"],
        }
        if sealed_reader is not None:
            shared["sealed_record_id"] = trial_reference["record_id"]
        attempts_made = 0
        try:
            run = None
            last_error: Exception | None = None
            for attempt in range(EPISODE_ATTEMPTS):
                attempts_made = attempt + 1
                try:
                    enforcer = build_enforcer(enforcer_name)
                    agent = SubjectAgent(
                        base_url=base_url,
                        api_key=api_key,
                        model=args.model,
                        temperature=PROTOCOL_TEMPERATURE,
                        max_turns=PROTOCOL_MAX_TURNS,
                        enable_thinking=False,
                        reasoning_effort=None,
                        seed=request_seed,
                        api_mode=api_mode,
                        parallel_tool_calls=PROTOCOL_PARALLEL_TOOL_CALLS,
                    )
                    run = run_agent_trial(trial, enforcer=enforcer, agent=agent)
                    break
                except Exception as exc:  # transient transport failures retry
                    last_error = exc
                    if attempt + 1 < EPISODE_ATTEMPTS:
                        time.sleep(EPISODE_BACKOFF_S[attempt])
            if run is None:
                raise last_error if last_error else RuntimeError("episode did not run")
            result = oracle.evaluate(trial, run)
            event_bytes = json.dumps(
                run["events"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            record = {
                **shared,
                "final_status": run["final_status"],
                "final_answer": run["final_answer"],
                "delivered": run["delivered"],
                "delivery_attempted": run["delivery_attempted"],
                "blocked_delivery": run["blocked_delivery"],
                "blocked_calls": run["blocked_calls"],
                "event_n": len(run["events"]),
                "event_sha256": hashlib.sha256(event_bytes).hexdigest(),
                "events": run["events"],
                "subject_trace": run["subject_trace"],
                "event_trace": [
                    {
                        key: event.get(key)
                        for key in (
                            "seq", "timestamp", "boundary", "app", "action",
                            "resource_id", "allowed", "reason",
                        )
                    }
                    for event in run["events"]
                ],
                "model_responses": run["model_responses"],
                "enforcer_error_n": len(getattr(enforcer, "errors", [])),
                "agent_error": run.get("error"),
                "oracle_result": result,
                "verbatim_violation": result["verbatim_violation"],
                "instrumented_violation": result["instrumented_violation"],
                "task_success": result["task_success"],
                "governed_task_pass": result["governed_task_pass"],
                "refusal": result["refusal"],
                "capability_failure": result["capability_failure"],
            }
        except Exception as exc:
            if is_transport_failure(exc):
                tripped_now = False
                failure = {
                    "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "enforcer": enforcer_name,
                    "reference_id": (
                        trial_reference.get("record_id")
                        or trial_reference.get("trial_id")
                    ),
                    "repeat": repeat,
                    "attempt_n": attempts_made,
                    **_failure_evidence(exc),
                }
                with lock:
                    manifest["transport"]["exhausted_episode_attempts"].append(
                        failure
                    )
                    breaker["streak"] += 1
                    breaker["skipped"] += 1
                    if breaker["streak"] >= TRANSPORT_ABORT_STREAK and not breaker["tripped"]:
                        breaker["tripped"] = True
                        breaker["reason"] = dict(failure)
                        tripped_now = True
                    _write_manifest(manifest_path, manifest)
                print(
                    "  EXHAUSTED "
                    f"{enforcer_name}/{failure['reference_id']}/r{repeat}: "
                    f"{failure['exception_type']} after {attempts_made} attempts",
                    flush=True,
                )
                if tripped_now:
                    print(
                        f"  ABORTING: {breaker['streak']} consecutive exhausted "
                        "transport episodes",
                        flush=True,
                    )
                return None
            record = {
                **shared,
                "error": f"{type(exc).__name__}: {exc}",
                "final_status": "harness_error",
            }
        with lock:
            breaker["streak"] = 0
            record = chain_record(
                record,
                chain_index=done["n"],
                previous_record_sha256=chain_state["previous"],
            )
            with output.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            chain_state["previous"] = record["record_sha256"]
            done["n"] += 1
            if done["n"] % 20 == 0 or done["n"] == len(all_tasks):
                print(f"  {done['n']}/{len(all_tasks)}", flush=True)
        return record

    try:
        with ThreadPoolExecutor(max_workers=PROTOCOL_CONCURRENCY) as executor:
            futures = [executor.submit(one, task) for task in tasks]
            for _ in as_completed(futures):
                pass
    finally:
        if sealed_reader is not None:
            sealed_reader.close()

    final_records = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    final_keys = [_episode_key(record) for record in final_records]
    final_key_set = set(final_keys)
    expected_key_set = {_task_episode_key(task) for task in all_tasks}
    unresolved_keys = sorted(expected_key_set - final_key_set)
    unexpected_keys = sorted(final_key_set - expected_key_set)
    unresolved_episode_keys = [
        {"enforcer": arm, "reference_id": reference_id, "repeat": repeat}
        for arm, reference_id, repeat in unresolved_keys
    ]
    unexpected_episode_keys = [
        {"enforcer": arm, "reference_id": reference_id, "repeat": repeat}
        for arm, reference_id, repeat in unexpected_keys
    ]
    exhausted_attempts = manifest["transport"]["exhausted_episode_attempts"]
    canonical_digest = lambda value: hashlib.sha256(  # noqa: E731
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    chain_head = verify_record_chain(final_records)
    observed_response_models = sorted({
        str(response.get("model"))
        for record in final_records
        for response in record.get("model_responses", [])
        if response.get("model")
    })
    response_metadata_complete = all(
        bool(record.get("model_responses"))
        and all(
            response.get("id") and response.get("model")
            for response in record.get("model_responses", [])
        )
        for record in final_records
        if "error" not in record
    )
    provider_response_ids = [
        str(response["id"])
        for record in final_records
        for response in record.get("model_responses", [])
        if response.get("id")
    ]
    provider_response_ids_unique = bool(
        response_metadata_complete
        and provider_response_ids
        and len(provider_response_ids) == len(set(provider_response_ids))
    )
    client_episode_sessions = []
    client_session_shape_valid = True
    for record in final_records:
        if "error" in record:
            continue
        sessions = {
            response.get("client_episode_session_id")
            for response in record.get("model_responses", [])
            if response.get("client_episode_session_id")
        }
        if len(sessions) != 1:
            client_session_shape_valid = False
        else:
            client_episode_sessions.append(next(iter(sessions)))
    client_episode_sessions_unique = bool(
        client_session_shape_valid
        and len(client_episode_sessions) == len(set(client_episode_sessions))
    )

    observed_system_fingerprints = sorted({
        str(response.get("system_fingerprint"))
        for record in final_records
        for response in record.get("model_responses", [])
        if response.get("system_fingerprint")
    })
    observed_decoding_requests = sorted(
        {
            json.dumps({
                key: response.get(key)
                for key in (
                    "api_mode", "request_temperature",
                    "request_temperature_sent", "request_seed_sent",
                    "request_enable_thinking", "request_enable_thinking_sent",
                    "reasoning_effort", "request_reasoning_sent",
                    "request_parallel_tool_calls",
                    "request_parallel_tool_calls_sent",
                )
            }, sort_keys=True, separators=(",", ":"))
            for record in final_records
            for response in record.get("model_responses", [])
        }
    )

    external_records = [
        record for record in final_records
        if str(record.get("enforcer", "")).startswith(("http://", "https://"))
        and "error" not in record
    ]
    enforcement_identities: set[tuple[str, str, str]] = {
        (str(identity["id"]), str(identity["version"]), str(identity["state_scope"]))
        for identity in config["built_in_enforcement_identities"]
    }
    enforcement_sessions = []
    enforcement_identity_complete = True
    for record in external_records:
        record_sessions = set()
        for event in record.get("events", []):
            if event.get("boundary") == "source_return_raw":
                continue
            metadata = event.get("decision_metadata", {})
            request_evidence = metadata.get("authzen_request", {})
            response_context = metadata.get("authzen_response_context", {})
            extension = response_context.get("accessbench", {})
            implementation = extension.get("implementation", {})
            if not implementation.get("id") or not implementation.get("version"):
                enforcement_identity_complete = False
                continue
            enforcement_identities.add((
                str(implementation["id"]),
                str(implementation["version"]),
                str(extension.get("state_scope", "undeclared")),
            ))
            if request_evidence.get("session_id"):
                record_sessions.add(request_evidence["session_id"])
        if len(record_sessions) != 1:
            enforcement_identity_complete = False
        else:
            enforcement_sessions.append(next(iter(record_sessions)))
    enforcement_session_isolation_observed = bool(
        enforcement_identity_complete
        and len(enforcement_sessions) == len(set(enforcement_sessions))
    )
    observed_enforcement_identities = [
        {"id": identity, "version": version, "state_scope": state_scope}
        for identity, version, state_scope in sorted(enforcement_identities)
    ]
    exact_matrix = (
        not unresolved_keys
        and not unexpected_keys
        and len(final_keys) == len(final_key_set)
    )
    transport_abort = {
        "tripped": bool(breaker["tripped"]),
        "reason": breaker["reason"] or None,
        "skipped_episode_n": breaker["skipped"],
    }
    manifest["transport"]["abort"] = transport_abort
    manifest.update({
        "status": "complete" if exact_matrix else "incomplete",
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "completed_episode_n": len(final_records),
        "error_episode_n": sum("error" in record for record in final_records),
        "duplicate_episode_key_n": len(final_keys) - len(set(final_keys)),
        "unresolved_episode_n": len(unresolved_episode_keys),
        "unresolved_episode_keys": unresolved_episode_keys,
        "unresolved_episode_keys_sha256": canonical_digest(
            unresolved_episode_keys
        ),
        "unexpected_episode_n": len(unexpected_episode_keys),
        "unexpected_episode_keys": unexpected_episode_keys,
        "unexpected_episode_keys_sha256": canonical_digest(
            unexpected_episode_keys
        ),
        "exhausted_episode_attempt_n": len(exhausted_attempts),
        "exhausted_episode_attempts_sha256": canonical_digest(
            exhausted_attempts
        ),
        "raw_sha256": _sha256_file(output),
        "raw_chain_head_sha256": chain_head,
        "observed_response_models": observed_response_models,
        "response_metadata_complete": response_metadata_complete,
        "provider_response_ids_unique": provider_response_ids_unique,
        "client_episode_sessions_unique": client_episode_sessions_unique,
        "observed_system_fingerprints": observed_system_fingerprints,
        "observed_decoding_requests": observed_decoding_requests,
        "observed_enforcement_identities": observed_enforcement_identities,
        "enforcement_identity_complete": enforcement_identity_complete,
        "enforcement_session_isolation_observed": (
            enforcement_session_isolation_observed
        ),
    })
    result_attestation_payload = {
        "schema_version": manifest["schema_version"],
        "pre_run_payload_sha256": manifest["pre_run_attestation"]["payload_sha256"],
        "config_commitment": manifest["config_commitment"],
        "raw_sha256": manifest["raw_sha256"],
        "raw_chain_head_sha256": manifest["raw_chain_head_sha256"],
        "completed_episode_n": manifest["completed_episode_n"],
        "error_episode_n": manifest["error_episode_n"],
        "duplicate_episode_key_n": manifest["duplicate_episode_key_n"],
        "unresolved_episode_n": manifest["unresolved_episode_n"],
        "unresolved_episode_keys_sha256": manifest[
            "unresolved_episode_keys_sha256"
        ],
        "unexpected_episode_n": manifest["unexpected_episode_n"],
        "unexpected_episode_keys_sha256": manifest[
            "unexpected_episode_keys_sha256"
        ],
        "exhausted_episode_attempt_n": manifest[
            "exhausted_episode_attempt_n"
        ],
        "exhausted_episode_attempts_sha256": manifest[
            "exhausted_episode_attempts_sha256"
        ],
        "transport_abort": transport_abort,
        "observed_response_models": observed_response_models,
        "response_metadata_complete": response_metadata_complete,
        "provider_response_ids_unique": provider_response_ids_unique,
        "client_episode_sessions_unique": client_episode_sessions_unique,
        "observed_system_fingerprints": observed_system_fingerprints,
        "observed_decoding_requests": observed_decoding_requests,
        "observed_enforcement_identities": observed_enforcement_identities,
        "enforcement_identity_complete": enforcement_identity_complete,
        "enforcement_session_isolation_observed": (
            enforcement_session_isolation_observed
        ),
        "status": manifest["status"],
    }
    manifest["result_attestation_payload"] = result_attestation_payload
    manifest["result_attestation"] = sign_attestation(
        result_attestation_payload,
        signing_key,
        purpose="accessbench-result-v1",
    )
    _write_manifest(manifest_path, manifest)
    if manifest["status"] == "complete":
        print(
            f"DONE {args.model}: {len(final_records)}/{len(all_tasks)} episodes at "
            f"{output}; manifest={manifest_path}",
            flush=True,
        )
        return
    print(
        f"INCOMPLETE {args.model}: {len(final_records)}/{len(all_tasks)} episodes; "
        f"unresolved={len(unresolved_episode_keys)} duplicate="
        f"{manifest['duplicate_episode_key_n']} unexpected="
        f"{len(unexpected_episode_keys)}. Resume with "
        f"ACCESSBENCH_RESUME_RAW={output}",
        flush=True,
    )
    raise SystemExit(3)


if __name__ == "__main__":
    main()
