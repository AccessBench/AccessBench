# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Orchestration for `accessbench-env run`, the main entry point.

Sequences the existing generate/demo/conformance/run_eval/aggregate steps
behind one command. Reimplements none of them: this module only chooses
defaults, checks preconditions early, and calls the real machinery in
`eval/run_eval.py` and `eval/aggregate.py` in-process, the same way the
existing test suite does.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from .calibrate import DEFAULT_CALIBRATION_DIR, ensure_judge_calibrated
from .evidence import (
    generate_signing_key,
    load_signing_key,
    public_key_id,
    sign_attestation,
)
from .generate import PUBLIC_SEED, build_catalog, load_phrase_bank
from .integrity_audit import (
    DEFAULT_JUDGE_SAMPLE_TARGET,
    assess_integrity,
    build_run_audit_record,
    stratified_episode_sample,
)
from .anti_cheat_judge import anti_cheat_judge_binding, run_anti_cheat_judge
from .oracle import evaluate
from .registry_executor import execute_registry
from .report_html import (
    enforced_arm_label,
    read_version,
    render_report,
    resolve_enforcement,
)
from .sandbox import Sandbox
from . import trust_registry
from .validate import read_jsonl, validate_catalog

LAB_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = LAB_ROOT / "eval"
PUBLIC_CATALOG = LAB_ROOT / "catalog" / "public.jsonl"
CORE_CATALOG = LAB_ROOT / "catalog" / "core_v2.jsonl"
RESULTS_RAW = LAB_ROOT / "results_raw"
RESULTS_ROOT = LAB_ROOT.parent / "results"
REPO_ROOT = LAB_ROOT.parent
DASHBOARD_SCRIPT = LAB_ROOT.parent / "dashboard" / "server.py"

DEFAULT_SMOKE_TRIALS = 6
FULL_CASE_N = 600
FULL_EPISODE_N = FULL_CASE_N * 2
# Measured token volume of one full paired run (1,200 episodes) on gpt-4o-class
# models, from the record. Scaled linearly for smoke samples.
MEASURED_PROMPT_TOKENS_PER_FULL_RUN = 2_700_000
MEASURED_COMPLETION_TOKENS_PER_FULL_RUN = 130_000
MIN_FREE_DISK_BYTES = 2 * 1024 ** 3
DEFAULT_MODEL_BASE_URL = "http://localhost:8000/v1"
BUNDLE_SCHEMA_VERSION = "accessbench-result-bundle-v1"
DEFAULT_DEMO_LIMIT = 6
DEFAULT_SIGNING_KEY = Path("~/.accessbench/signing-key.pem").expanduser()


@contextlib.contextmanager
def _argv(argv: list[str]):
    previous = sys.argv
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = previous


def _ensure_eval_on_path() -> None:
    path = str(EVAL_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


def ensure_public_catalog() -> None:
    """Generate `catalog/public.jsonl` if it is not already there."""
    if PUBLIC_CATALOG.exists():
        return
    print(f"generating public catalog at {PUBLIC_CATALOG} ...")
    trials = build_catalog(split="public", seed=PUBLIC_SEED, phrase_bank=load_phrase_bank(None))
    summary = validate_catalog(trials)
    if not summary["ok"]:
        raise SystemExit("generated public catalog failed validation")
    PUBLIC_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    with PUBLIC_CATALOG.open("w", encoding="utf-8", newline="\n") as handle:
        for row in trials:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    print(f"wrote {len(trials)} trials")


def demo_sample(limit: int = DEFAULT_DEMO_LIMIT) -> None:
    """Replay a handful of core-panel cases with no enforcement, to prove the grader.

    The reference plan attempts every case's raw requested action with no
    enforcement layer in the way. On the panel's allowed half that completes
    cleanly; on its forbidden half it correctly triggers a violation, which is
    what the deterministic grader is supposed to catch. Every case must land
    in exactly one bucket; anything else means the grader is broken.
    """
    trials = read_jsonl(str(CORE_CATALOG))
    sample = trials[:limit]
    print(f"replaying {len(sample)} of {len(trials)} core-panel cases through the reference plan ...")
    clean = 0
    violations = 0
    for trial in sample:
        run = Sandbox(trial).run_reference()
        result = evaluate(trial, run)
        if result["governed_task_pass"]:
            clean += 1
        elif result["instrumented_violation"]:
            violations += 1
    if clean + violations != len(sample):
        raise SystemExit(
            "grader proof failed: some cases neither completed cleanly nor "
            "triggered a detected violation"
        )
    print(
        f"reference plan: {clean}/{len(sample)} completed cleanly, "
        f"{violations}/{len(sample)} correctly triggered a detected violation "
        "-- the grader is telling allowed and forbidden cases apart"
    )


def check_conformance(enforcement: str) -> None:
    """Fail fast on a broken enforcement endpoint before a run spends anything."""
    if "://" not in enforcement:
        return  # a built-in enforcement name, not an external URL
    from .conformance import run_conformance

    print(f"checking conformance of {enforcement} ...")
    report = run_conformance(
        enforcement,
        timeout=15.0,
        bearer_token=os.environ.get("ACCESSBENCH_ENFORCEMENT_BEARER_TOKEN") or None,
    )
    if not report["ok"]:
        raise SystemExit(
            "enforcement endpoint did not pass conformance; run "
            f"`accessbench conformance --enforcement {enforcement}` for detail"
        )
    print("conformance: ok")


def ensure_signing_key(explicit: str | None) -> str:
    """Point ACCESSBENCH_SIGNING_KEY at a usable key, provisioning one if needed."""
    if explicit:
        os.environ["ACCESSBENCH_SIGNING_KEY"] = explicit
        return explicit
    existing = os.environ.get("ACCESSBENCH_SIGNING_KEY")
    if existing:
        return existing
    if not DEFAULT_SIGNING_KEY.exists():
        print(f"no signing key found; generating one at {DEFAULT_SIGNING_KEY}")
        generate_signing_key(DEFAULT_SIGNING_KEY)
    os.environ["ACCESSBENCH_SIGNING_KEY"] = str(DEFAULT_SIGNING_KEY)
    return str(DEFAULT_SIGNING_KEY)


TRUST_PURPOSES_FOR_FULL_RUN = (
    "accessbench-anti-cheat-assessment-v1",
    "accessbench-pre-run-v1",
    "accessbench-result-v1",
)


def check_signing_key_trust(
    signing_key_path: str,
    *,
    registry_path: Path = trust_registry.DEFAULT_REGISTRY_PATH,
) -> str:
    """Report whether this run's signing key is listed in TRUSTED_KEYS.json.

    Listing is a recorded admission by the maintainers, not independent
    validation; the registry is maintainer-controlled until an outside party
    holds part of it, and every message here says so.

    Never adds the key automatically: publication requires the key ID to
    appear in `TRUSTED_KEYS.json` (see trust_registry.py), admitted through
    a deliberate, git-recorded commit, not a runtime side effect of running
    the benchmark. A run with an untrusted key still completes; aggregate.py
    is what marks the result not publication-eligible, the same way it
    already does for any other untrusted signature.
    """
    key_id = public_key_id(load_signing_key(signing_key_path).public_key())
    missing = [
        purpose for purpose in TRUST_PURPOSES_FOR_FULL_RUN
        if not trust_registry.is_key_trusted(key_id, purpose, path=registry_path)
    ]
    if missing:
        print(
            f"signing key {key_id} is not in the trusted-key registry for: "
            f"{', '.join(missing)}."
        )
        print(
            "  this run will complete, but its sidecar/manifest will read as "
            "untrusted and the result will not be publication-eligible."
        )
        print(
            "  to admit it: accessbench-env trust add-key --key-id "
            f"{key_id} --owner \"YOUR NAME\" "
            f"--purpose {' --purpose '.join(TRUST_PURPOSES_FOR_FULL_RUN)}"
        )
    else:
        print(
            f"signing key {key_id}: listed in TRUSTED_KEYS.json for this run "
            "(maintainer-controlled registry; a recorded admission, not "
            "independent validation)"
        )
    return key_id


def _observed_hosts() -> list[str]:
    from urllib.parse import urlparse

    hosts = []
    for env_var in ("ACCESSBENCH_MODEL_BASE_URL", "ACCESSBENCH_JUDGE_MODEL_BASE_URL"):
        base_url = os.environ.get(env_var, "")
        host = urlparse(base_url).hostname if base_url else None
        if host:
            hosts.append(host)
    return hosts or ["localhost"]


def run_eval_arm(model: str, enforcement: str, full: bool) -> Path:
    """Run run_eval.main() in-process and return the new raw evidence path."""
    _ensure_eval_on_path()
    import run_eval  # top-level module in eval/, matches the existing test suite
    from .isolation_observer import IsolationObserver

    before = {p.name for p in RESULTS_RAW.glob("*.jsonl")} if RESULTS_RAW.exists() else set()
    if full:
        os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
    else:
        os.environ.setdefault("ACCESSBENCH_SMOKE_TRIALS", str(DEFAULT_SMOKE_TRIALS))
    argv = ["run_eval.py", "--model", model, "--enforcement", enforcement]
    resume_raw = os.environ.get("ACCESSBENCH_RESUME_RAW", "").strip()
    observer = IsolationObserver(_observed_hosts())
    with observer, _argv(argv):
        run_eval.main()
    if resume_raw:
        raw_path = Path(resume_raw)  # the runner appended to the retained raw, no new file
    else:
        after = {p.name for p in RESULTS_RAW.glob("*.jsonl")}
        new = sorted(after - before)
        if not new:
            raise SystemExit("run completed but no new raw file appeared in results_raw/")
        raw_path = RESULTS_RAW / new[-1]
    isolation_report_path = Path(str(raw_path) + ".isolation.json")
    isolation_report_path.write_text(
        json.dumps(observer.report(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return raw_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _judge_complete(model: str):
    """Build a completion function for `run_anti_cheat_judge` against a live model.

    Reuses the same operator-supplied endpoint as the subject agent
    (ACCESSBENCH_MODEL_BASE_URL / OPENAI_API_KEY): the Judge is just another
    model call, not a special client. Tries strict JSON-schema structured
    output first, since the frozen response schema is strict-mode compatible;
    falls back to json_object mode for endpoints that reject json_schema.
    """
    from openai import OpenAI

    base_url = os.environ.get("ACCESSBENCH_MODEL_BASE_URL", "http://localhost:8000/v1")
    client = OpenAI(
        base_url=base_url,
        api_key=os.environ.get("OPENAI_API_KEY", "local-no-key"),
        max_retries=int(os.environ.get("ACCESSBENCH_MODEL_MAX_RETRIES", "6")),
        timeout=float(os.environ.get("ACCESSBENCH_MODEL_TIMEOUT_S", "180")),
    )

    def complete(request: dict) -> str:
        kwargs = dict(
            model=request["model"],
            temperature=request["temperature"],
            messages=request["messages"],
        )
        try:
            response = client.chat.completions.create(
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "accessbench_anti_cheat_judge",
                        "schema": request["response_schema"],
                        "strict": True,
                    },
                },
                **kwargs,
            )
        except Exception:
            response = client.chat.completions.create(
                response_format={"type": "json_object"}, **kwargs
            )
        return response.choices[0].message.content

    return complete


def ensure_judge_calibrated_for_run(judge_model: str, *, force: bool = False) -> dict:
    """Calibrate `judge_model` if needed, or reuse a cached passing result.

    Raises SystemExit (never proceeds) if calibration fails, whether fresh or
    previously cached: see calibrate.ensure_judge_calibrated for why.
    """
    return ensure_judge_calibrated(
        judge_model,
        _judge_complete(judge_model),
        force=force,
        cache_dir=DEFAULT_CALIBRATION_DIR,
    )


def run_integrity_audit(
    raw_path: Path,
    judge_model: str,
    *,
    judge_sample_target: int = DEFAULT_JUDGE_SAMPLE_TARGET,
    judge_sample_seed: int = 0,
    calibration_report: dict | None = None,
) -> Path:
    """Assemble, sign, and write the `<raw>.integrity.json` Anti-Cheat sidecar.

    Runs the deterministic protocol-check registry over the whole raw file,
    reviews a deterministic stratified sample of episodes with the Anti-Cheat
    Judge in one consolidated audit record (every episode, if the run is at
    or below the sample target), and combines both into a single signed
    run-level assessment. A run above the target is not reviewed in full: at
    --full scale (1,200 episodes) a whole-run audit record is on the order
    of millions of tokens, well past what a single Judge call can take, and
    coverage of what only the Judge can catch does not need every episode
    when the registry checks already give exhaustive, free coverage of
    everything that is mechanically decidable. See
    `integrity_audit.stratified_episode_sample`. `aggregate.py` treats a
    missing sidecar as fully Ineligible, so a `--full` run is not
    publication-eligible without this step.

    `calibration_report` should be the passing report from
    `ensure_judge_calibrated_for_run` for this exact `judge_model`; when
    supplied, `anti_cheat_judge_calibration` reports pass with the report's
    own digest as evidence instead of the registry's default not_run.
    """
    manifest_path = Path(str(raw_path) + ".manifest.json")
    registry = execute_registry(raw_path, manifest_path)
    records = read_jsonl(str(raw_path))
    sample = stratified_episode_sample(
        records, target=judge_sample_target, seed=judge_sample_seed
    )
    audit_record = build_run_audit_record(sample, total_episode_count=len(records))

    protocol_checks = dict(registry["protocol_checks"])
    protocol_check_evidence = dict(registry["protocol_check_evidence"])

    judge_error: str | None = None
    binding = None
    findings: list = []
    try:
        judge_output = run_anti_cheat_judge(
            audit_record, model=judge_model, complete=_judge_complete(judge_model)
        )
        binding = anti_cheat_judge_binding(judge_output)
        findings = judge_output["findings"]
        judge_state = "pass"
        judge_detail = (
            f"Anti-Cheat Judge reviewed {audit_record['episode_count']} of "
            f"{audit_record['total_episode_count']} episodes"
        )
    except Exception as exc:
        judge_error = f"{type(exc).__name__}: {exc}"
        judge_state = "error"
        judge_detail = f"Anti-Cheat Judge did not complete: {judge_error}"
    protocol_checks["anti_cheat_judge_completed"] = judge_state
    protocol_check_evidence["anti_cheat_judge_completed"] = {
        "executor_id": "accessbench-env-run-command",
        "executor_version": "1",
        "evidence_sha256": hashlib.sha256(judge_detail.encode()).hexdigest(),
    }

    if calibration_report is not None and calibration_report.get("gate") == "PASS":
        calibration_detail = (
            f"judge {judge_model!r} calibrated at "
            f"{calibration_report.get('calibrated_at')}: precision "
            f"{calibration_report.get('precision')} on "
            f"{calibration_report.get('n')} fixtures"
        )
        protocol_checks["anti_cheat_judge_calibration"] = "pass"
        protocol_check_evidence["anti_cheat_judge_calibration"] = {
            "executor_id": "accessbench-env-calibrate",
            "executor_version": "1",
            "evidence_sha256": hashlib.sha256(calibration_detail.encode()).hexdigest(),
        }

    assessment = assess_integrity(
        protocol_checks=protocol_checks,
        protocol_check_evidence=protocol_check_evidence,
        audit_record=audit_record,
        raw_findings=findings,
        anti_cheat_judge_error=judge_error,
        anti_cheat_judge_binding=binding,
        trusted_reviewer_key_ids=(),
    )

    signing_key_path = os.environ["ACCESSBENCH_SIGNING_KEY"]
    private_key = load_signing_key(signing_key_path)
    payload = {
        "raw_sha256": _sha256_file(raw_path),
        "run_manifest_sha256": _sha256_file(manifest_path),
        "assessment": assessment,
    }
    sidecar = {
        "attestation_payload": payload,
        "attestation": sign_attestation(
            payload, private_key, purpose="accessbench-anti-cheat-assessment-v1"
        ),
    }
    sidecar_path = Path(str(raw_path) + ".integrity.json")
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    return sidecar_path


def aggregate_raw(raw_path: Path) -> Path:
    """Run aggregate.main() in-process and return the results root directory."""
    _ensure_eval_on_path()
    import aggregate as aggregate_module

    stamp = time.strftime("%Y%m%d-%H%M%S")
    argv = ["aggregate.py", "--raw", str(raw_path), "--stamp", stamp]
    with _argv(argv):
        aggregate_module.main()
    return RESULTS_ROOT


def dashboard_hint() -> tuple[str, str]:
    port = os.environ.get("ACCESSBENCH_DASHBOARD_PORT", "8000")
    return f"python3 {DASHBOARD_SCRIPT}", f"http://localhost:{port}"


# ---------------------------------------------------------------------------
# Public golden path: alias, resume, preflight, spend estimate, result bundle.
# Everything below is a thin layer over the runner and aggregator above; it
# changes no benchmark semantics and writes nothing into summary.json.
# ---------------------------------------------------------------------------


def resolve_enforcement_arg(value: str) -> tuple[str, str | None]:
    """Resolve the public `benchmark` alias before the runner sees it.

    Evidence therefore records the real built-in id; the alias is kept only
    for run.json and the resume command.
    """
    resolved, alias = resolve_enforcement(value)
    if alias:
        print(
            f"enforcement: {alias} -> {resolved} "
            "(the Benchmark PDP, reference decision point)"
        )
    return resolved, alias


def model_base_url() -> str:
    return os.environ.get("ACCESSBENCH_MODEL_BASE_URL", DEFAULT_MODEL_BASE_URL)


def is_local_endpoint(base_url: str) -> bool:
    """Reuse the runner's own notion of a non-billing endpoint when importable."""
    try:
        _ensure_eval_on_path()
        import run_eval

        return bool(run_eval._is_local_endpoint(base_url))
    except Exception:
        from urllib.parse import urlparse

        host = (urlparse(base_url).hostname or "").lower()
        return (
            host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
            or host.startswith(("10.", "192.168."))
            or any(host.startswith(f"172.{n}.") for n in range(16, 32))
            or host.endswith((".local", ".internal", ".lan"))
        )


def prepare_resume(raw: str) -> Path:
    """Point the runner at a retained raw file; refuse a path that is not there."""
    path = Path(raw).expanduser()
    manifest = Path(str(path) + ".manifest.json")
    if not path.exists():
        raise SystemExit(
            f"--resume: {path} does not exist. Pass the raw .jsonl path the "
            "interrupted run printed (it lives under environment_lab/results_raw/); "
            "its .manifest.json must sit beside it."
        )
    if not manifest.exists():
        raise SystemExit(
            f"--resume: {manifest} is missing; the runner cannot continue a raw "
            "file without its manifest."
        )
    resolved = path.resolve()
    os.environ["ACCESSBENCH_RESUME_RAW"] = str(resolved)
    print(f"resume: continuing {resolved.name}")
    return resolved


def resume_command(model: str, enforcement_arg: str, full: bool, raw_path: Path) -> str:
    full_flag = " --full" if full else ""
    return (
        f"accessbench run --model {model} --enforcement {enforcement_arg}"
        f"{full_flag} --resume {Path(raw_path).resolve()}"
    )


def snapshot_raws() -> set[str]:
    return {p.name for p in RESULTS_RAW.glob("*.jsonl")} if RESULTS_RAW.exists() else set()


def snapshot_results() -> set[str]:
    return {p.name for p in RESULTS_ROOT.iterdir()} if RESULTS_ROOT.exists() else set()


def resume_candidate(raws_before: set[str], resume: str | None) -> Path | None:
    """The raw file a failed or aborted run left behind, if any."""
    if resume:
        return Path(resume).expanduser().resolve()
    new = sorted(snapshot_raws() - raws_before)
    return RESULTS_RAW / new[-1] if new else None


def preflight_credentials() -> None:
    base = model_base_url()
    if is_local_endpoint(base):
        print(f"preflight: credentials: ok (local endpoint {base}, nothing billed)")
        return
    missing = []
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append(
            "OPENAI_API_KEY is not set; export OPENAI_API_KEY=<your provider key>"
        )
    if os.environ.get("ACCESSBENCH_SPEND_APPROVED") != "yes":
        missing.append(
            "ACCESSBENCH_SPEND_APPROVED is not 'yes'; export "
            "ACCESSBENCH_SPEND_APPROVED=yes once the spend for this specific run is approved"
        )
    if missing:
        raise SystemExit(
            f"preflight: credentials: FAILED for hosted endpoint {base}:\n  "
            + "\n  ".join(missing)
        )
    print(f"preflight: credentials: ok (hosted endpoint {base}, spend approved)")


def preflight_disk(min_free_bytes: int = MIN_FREE_DISK_BYTES) -> None:
    RESULTS_RAW.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(RESULTS_RAW)
    free_gb = usage.free / 1024 ** 3
    if usage.free < min_free_bytes:
        raise SystemExit(
            f"preflight: disk: FAILED, {free_gb:.1f} GB free on the filesystem "
            f"holding {RESULTS_RAW}; at least {min_free_bytes / 1024 ** 3:.0f} GB is "
            "needed for raw evidence. Free space or move the checkout."
        )
    print(f"preflight: disk: ok ({free_gb:.1f} GB free on the filesystem holding results_raw)")


def preflight_model_tool_use(model: str) -> None:
    """One tiny chat-completions request that must come back as a tool call.

    Same client construction as `_judge_complete` and the subject agent. On a
    hosted endpoint this is one cheap request, and it runs only after the
    credential check, so spend is already approved.
    """
    from openai import OpenAI

    base_url = model_base_url()
    client = OpenAI(
        base_url=base_url,
        api_key=os.environ.get("OPENAI_API_KEY", "local-no-key"),
        max_retries=int(os.environ.get("ACCESSBENCH_MODEL_MAX_RETRIES", "6")),
        timeout=float(os.environ.get("ACCESSBENCH_MODEL_TIMEOUT_S", "180")),
    )
    tool = {
        "type": "function",
        "function": {
            "name": "record_check",
            "description": "Record that the preflight check ran.",
            "parameters": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
    }
    request: dict = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a tool-using assistant. Call the record_check tool "
                    "with ok=true. Do not answer in prose."
                ),
            },
            {"role": "user", "content": "Run the check."},
        ],
        "tools": [tool],
    }
    if "api.openai.com" in base_url:
        request["max_completion_tokens"] = 64
        request["store"] = False
    else:
        request["temperature"] = 0
        request["max_tokens"] = 64
    hint = (
        "Check ACCESSBENCH_MODEL_BASE_URL, the model id, and that the server has "
        "tool calling enabled. Use --skip-model-preflight only if you have already "
        "proven this endpoint."
    )
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        raise SystemExit(
            f"preflight: model tool use: FAILED, {base_url} rejected a tiny "
            f"chat-completions request for {model}: {type(exc).__name__}: {exc}. {hint}"
        )
    calls = getattr(response.choices[0].message, "tool_calls", None) or []
    names = [getattr(getattr(c, "function", None), "name", None) for c in calls]
    if "record_check" not in names:
        raise SystemExit(
            f"preflight: model tool use: FAILED, {model} at {base_url} answered "
            f"without a structured tool call (got {names or 'no tool calls'}). {hint}"
        )
    print("preflight: model tool use: ok (structured tool call returned)")


def preflight(
    *,
    enforcement: str,
    signing_key: str | None,
    model: str,
    skip_model_preflight: bool = False,
) -> str:
    """Every check that can fail, in order, before any inference is paid for."""
    signing_key_path = ensure_signing_key(signing_key)
    print(f"preflight: signing key: ok ({signing_key_path})")
    preflight_credentials()
    preflight_disk()
    check_conformance(enforcement)
    if "://" in enforcement:
        print("preflight: pdp conformance: ok")
    else:
        print(f"preflight: pdp conformance: ok (built-in {enforcement}, no endpoint to probe)")
    if skip_model_preflight:
        print("preflight: model tool use: skipped (--skip-model-preflight)")
    else:
        preflight_model_tool_use(model)
    return signing_key_path


def smoke_trial_n() -> int:
    raw = os.environ.get("ACCESSBENCH_SMOKE_TRIALS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_SMOKE_TRIALS


def print_spend_estimate(full: bool) -> None:
    """Three lines on expected hosted spend; nothing for a local endpoint."""
    base = model_base_url()
    if is_local_endpoint(base):
        return
    if full:
        episodes = FULL_EPISODE_N
        shape = f"full: {FULL_CASE_N} cases x 2 arms = {FULL_EPISODE_N:,} episodes"
    else:
        n = smoke_trial_n()
        episodes = n * 2
        shape = f"smoke: {n} cases x 2 arms = {episodes} episodes"
    scale = episodes / FULL_EPISODE_N
    prompt_m = MEASURED_PROMPT_TOKENS_PER_FULL_RUN * scale / 1e6
    completion_m = MEASURED_COMPLETION_TOKENS_PER_FULL_RUN * scale / 1e6
    print(f"estimated hosted spend: {shape} against {base}")
    print(
        "  measured volume of one full paired run on gpt-4o-class models: about "
        "2.7M prompt and 0.13M completion tokens per 1,200 episodes; scaled to this "
        f"run: about {prompt_m:.2f}M prompt and {completion_m:.3f}M completion tokens"
    )
    price_in = os.environ.get("ACCESSBENCH_PRICE_PER_M_INPUT", "").strip()
    price_out = os.environ.get("ACCESSBENCH_PRICE_PER_M_OUTPUT", "").strip()
    try:
        usd = prompt_m * float(price_in) + completion_m * float(price_out)
    except ValueError:
        usd = None
    if usd is not None:
        print(
            f"  at the rates you set (USD {price_in}/M input, USD {price_out}/M "
            f"output): about USD {usd:.2f}; multiply by your provider's price if "
            "those differ, AccessBench does not know your rate"
        )
    else:
        print(
            "  multiply by your provider's price; AccessBench does not know your "
            "rate (set ACCESSBENCH_PRICE_PER_M_INPUT and ACCESSBENCH_PRICE_PER_M_OUTPUT, "
            "USD per million tokens, for a dollar estimate)"
        )


def find_new_result_dir(results_before: set[str], raw_path: Path | None = None) -> Path:
    """The results/<run_id>/ directory this run's aggregation just produced.

    Prefers the new directory whose summary.json binds this raw file's digest,
    so a concurrent aggregation in the same checkout cannot be mistaken for
    ours; falls back to the newest new directory.
    """
    new = sorted(
        p for p in RESULTS_ROOT.iterdir()
        if p.is_dir() and p.name not in results_before and (p / "summary.json").exists()
    )
    if not new:
        raise SystemExit("aggregation finished but no new results/<run_id>/ directory appeared")
    if raw_path is not None:
        raw_sha = _sha256_file(Path(raw_path))
        for candidate in reversed(new):
            try:
                meta = json.loads((candidate / "summary.json").read_text(encoding="utf-8")).get("meta", {})
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("raw_sha256") == raw_sha:
                return candidate
    return new[-1]


def build_bundle(
    result_dir: Path,
    raw_path: Path,
    *,
    argv: list[str],
    enforcement: str,
    enforcement_alias: str | None,
) -> dict[str, Path]:
    """Make results/<run_id>/ self-contained: evidence/, run.json, report.html, VERIFY.txt.

    summary.json is never touched. The dashboard reads results/*/summary.json
    only, so the extra files are harmless to it.
    """
    result_dir = Path(result_dir).resolve()
    raw_path = Path(raw_path)
    manifest_path = Path(str(raw_path) + ".manifest.json")
    sidecar_path = Path(str(raw_path) + ".integrity.json")
    evidence_dir = result_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Path] = {}
    for source in (raw_path, manifest_path, sidecar_path):
        if source.exists():
            target = evidence_dir / source.name
            shutil.copy2(source, target)
            copied[source.name] = target
    evidence_sha = {name: _sha256_file(path) for name, path in sorted(copied.items())}
    summary_path = result_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    run_json = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "run_id": result_dir.name,
        "config": manifest.get("config", {}),
        "enforcement": {
            "resolved_id": enforcement,
            "alias_used": enforcement_alias,
            "arm_label": enforced_arm_label(enforcement),
        },
        "cli_argv": list(argv),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "bundled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "evidence_sha256": evidence_sha,
        "summary_sha256": _sha256_file(summary_path),
    }
    (result_dir / "run.json").write_text(
        json.dumps(run_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    digests = {
        "summary.json": run_json["summary_sha256"],
        f"evidence/{raw_path.name}": evidence_sha.get(raw_path.name, ""),
        f"evidence/{manifest_path.name}": evidence_sha.get(manifest_path.name, ""),
    }
    report = render_report(
        summary,
        manifest,
        bundle_path=str(result_dir),
        digests=digests,
        version=read_version(REPO_ROOT),
    )
    (result_dir / "report.html").write_text(report, encoding="utf-8")

    verify_lines = [
        f"accessbench verify {result_dir}",
        "",
        "sha256 digests at bundle time:",
    ] + [f"  {name}  {digest}" for name, digest in digests.items()]
    (result_dir / "VERIFY.txt").write_text("\n".join(verify_lines) + "\n", encoding="utf-8")
    return {
        "bundle": result_dir,
        "evidence": evidence_dir,
        "run_json": result_dir / "run.json",
        "report": result_dir / "report.html",
        "verify": result_dir / "VERIFY.txt",
    }
