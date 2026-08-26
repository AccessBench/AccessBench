# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Command line interface for generation, validation, and smoke execution."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path

from .generate import PUBLIC_SEED, build_catalog, load_phrase_bank
from .evidence import generate_signing_key
from .oracle import evaluate
from . import review_attestation
from . import run_command
from . import trust_registry
from . import verify_result as verify_result_module
from .report_html import SMOKE_WARNING
from .panel import (
    build_core_panel,
    core_panel_manifest,
    shortcut_control_report,
    validate_core_panel,
)
from .sandbox import Sandbox
from .validate import compare_splits, file_sha256, read_jsonl, validate_catalog


def _write_jsonl(path: str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _read_seed(path: str | None, split: str) -> str:
    if split == "public":
        return PUBLIC_SEED
    if path is None:
        raise SystemExit("heldout generation requires --seed-file")
    _require_private_file(path, "heldout seed")
    seed = Path(path).read_text(encoding="utf-8").strip()
    if len(seed) < 24:
        raise SystemExit("heldout seed must contain at least 24 characters")
    return seed


def _require_private_file(path: str, label: str) -> None:
    mode = stat.S_IMODE(Path(path).stat().st_mode)
    if mode & 0o077:
        raise SystemExit(
            f"{label} must not be readable or writable by group or others"
        )


def command_generate(args: argparse.Namespace) -> None:
    seed = _read_seed(args.seed_file, args.split)
    if args.split == "heldout":
        if args.phrase_bank is None:
            raise SystemExit("heldout generation requires --phrase-bank")
        _require_private_file(args.phrase_bank, "heldout phrase bank")
    phrase_bank = load_phrase_bank(args.phrase_bank)
    trials = build_catalog(split=args.split, seed=seed, phrase_bank=phrase_bank)
    summary = validate_catalog(trials)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["ok"]:
        raise SystemExit("catalog validation failed; output was not written")
    _write_jsonl(args.out, trials)
    if args.split == "heldout":
        Path(args.out).chmod(0o600)
    print(f"wrote {len(trials)} trials to {args.out}")


def command_validate(args: argparse.Namespace) -> None:
    trials = read_jsonl(args.catalog)
    summary = validate_catalog(trials)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["ok"]:
        raise SystemExit(1)


def command_validate_core(args: argparse.Namespace) -> None:
    """Validate an admitted panel against its fully validated source matrix."""
    source = read_jsonl(args.source)
    source_validation = validate_catalog(source)
    if not source_validation["ok"]:
        raise SystemExit("source construction matrix failed validation")
    admitted = read_jsonl(args.catalog)
    expected = build_core_panel(source)
    validate_core_panel(admitted)
    if admitted != expected:
        raise SystemExit("admitted core panel differs from deterministic rebuild")
    report = core_panel_manifest(source)
    report.update({
        "ok": True,
        "catalog_sha256": file_sha256(args.catalog),
        "source_sha256": file_sha256(args.source),
    })
    print(json.dumps(report, indent=2, sort_keys=True))


def command_compare(args: argparse.Namespace) -> None:
    public = read_jsonl(args.public)
    heldout = read_jsonl(args.heldout)
    failures = compare_splits(public, heldout)
    report = {
        "ok": not failures,
        "failures": failures,
        "public_trial_n": len(public),
        "heldout_trial_n": len(heldout),
        "public_prompt_n": len({t["prompt"] for t in public}),
        "heldout_prompt_n": len({t["prompt"] for t in heldout}),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


def command_demo(args: argparse.Namespace) -> None:
    """Free, offline: replay a few cases through the reference plan and the grader.

    Reads the tracked core catalog only; it never builds the 100 MB public
    construction matrix, which only `run` and `generate` need.
    """
    trials = read_jsonl(args.catalog)
    rows = []
    for trial in trials[: args.limit]:
        run = Sandbox(trial).run_reference()
        result = evaluate(trial, run)
        rows.append({
            "trial_id": trial["trial_id"],
            "mechanism": trial["mechanism"],
            "profile": trial["enterprise_profile_id"],
            "flow_variant": trial["flow_variant"],
            "verbatim_violation": result["verbatim_violation"],
            "instrumented_violation": result["instrumented_violation"],
            "task_success": result["task_success"],
            "governed_task_pass": result["governed_task_pass"],
            "refusal": result["refusal"],
        })
    print(json.dumps(rows, indent=2, sort_keys=True))
    print()
    print(
        f"demo done: {len(rows)} cases replayed offline through the reference plan "
        "and the deterministic grader. This was a zero-cost grader proof, not a "
        "benchmark result; no model was called. Next: accessbench run --model "
        "MODEL --enforcement benchmark"
    )


def command_manifest(args: argparse.Namespace) -> None:
    public = read_jsonl(args.public)
    heldout = read_jsonl(args.heldout)
    comparison = compare_splits(public, heldout)
    def structure(rows: list[dict]) -> Counter:
        return Counter(
            (
                row["blueprint_id"],
                row["surface"],
                row["carrier_style"],
                row["flow_variant"],
                row["enterprise_profile_id"],
            )
            for row in rows
        )

    manifest = {
        "schema_version": "contamination-manifest-v3",
        "public": {
            "path": Path(args.public).name,
            "sha256": file_sha256(args.public),
            "trial_n": len(public),
            "prompt_n": len({t["prompt"] for t in public}),
            "seed_commitment": sorted({t["seed_commitment"] for t in public}),
            "scenario_versions": sorted({t["scenario_version"] for t in public}),
            "oracle_versions": sorted({t["oracle_version"] for t in public}),
        },
        "heldout": {
            "path": "withheld",
            "sha256": file_sha256(args.heldout),
            "trial_n": len(heldout),
            "prompt_n": len({t["prompt"] for t in heldout}),
            "scenario_versions": sorted({t["scenario_version"] for t in heldout}),
            "oracle_versions": sorted({t["oracle_version"] for t in heldout}),
        },
        "split_validation": {
            "ok": not comparison,
            "failures": comparison,
            "seed_disjoint": not any(
                t["seed_commitment"] == heldout[0]["seed_commitment"] for t in public
            ),
            "prompt_disjoint": not bool(
                {t["prompt"] for t in public} & {t["prompt"] for t in heldout}
            ),
            "world_disjoint": not bool(
                {t["world_id"] for t in public} & {t["world_id"] for t in heldout}
            ),
            "structural_coverage_identical": structure(public) == structure(heldout),
        },
        "release_rule": "Do not publish heldout prompts, worlds, seed material, private phrase banks, or plaintext asset digests.",
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if comparison:
        raise SystemExit(1)


def command_generate_signing_key(args: argparse.Namespace) -> None:
    """Provision evaluator infrastructure without changing benchmark inputs."""
    key_id = generate_signing_key(args.out)
    print(json.dumps({
        "algorithm": "Ed25519",
        "key_id": key_id,
        "private_key_path": str(Path(args.out).expanduser().resolve()),
    }, indent=2, sort_keys=True))



def command_attest_review(args: argparse.Namespace) -> None:
    """Sign a record that a named reviewer read this exact development bank."""
    digests = review_attestation.bank_digests(args.catalog, args.manifest)
    known = set(review_attestation.catalog_trial_ids(args.catalog))
    unknown = sorted(set(args.exception or []) - known)
    if unknown:
        raise SystemExit("exception case ids not in the catalog: " + ", ".join(unknown))
    try:
        payload = review_attestation.build_payload(
            digests,
            reviewer=args.reviewer,
            decision=args.decision,
            date=args.date,
            exceptions=args.exception or [],
            role=args.role,
            note=args.note or "",
        )
    except ValueError as exc:
        raise SystemExit(f"attest-review: {exc}")
    key_path = run_command.ensure_signing_key(args.signing_key)
    record = review_attestation.sign_review(payload, review_attestation.load_private_key(key_path))
    try:
        path = review_attestation.write_review(record, args.out_dir)
    except FileExistsError as exc:
        raise SystemExit(str(exc))
    print(json.dumps({
        "record": str(path),
        "key_id": record["attestation"]["key_id"],
        "panel_id": payload["panel_id"],
        "prompt_set_sha256": payload["prompt_set_sha256"],
        "reviewer": payload["reviewer"],
        "decision": payload["decision"],
        "date": payload["date"],
        "exceptions": payload["exceptions"],
    }, indent=2, sort_keys=True))
    print()
    print(
        "signed. This records maintainer review of the exact bank named above; "
        "it is not independent validation. Commit the record and have each "
        "reviewer sign their own with their own key. Check it with: "
        f"accessbench verify-review {path}"
    )


def command_verify_review(args: argparse.Namespace) -> None:
    """Check a bank review record: shape, signature, digest binding, fields."""
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"verify-review: cannot read {args.record}: {exc}")
    trusted = trust_registry.trusted_key_ids_for(
        review_attestation.PURPOSE, "ACCESSBENCH_TRUSTED_REVIEWER_KEY_IDS",
    )
    result = review_attestation.verify_review(
        record, catalog=args.catalog, manifest=args.manifest, trusted_key_ids=trusted,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            print(f"{item['status']} {item['check']}: {item['detail']}")
        print()
        if result["ok"]:
            print(
                f"result: VERIFIED, {result['reviewer']} {result['decision']} on "
                f"{result['date']}; maintainer review of this exact bank, not "
                "independent validation"
            )
        else:
            failed = sum(1 for item in result["checks"] if item["status"] == "FAIL")
            print(f"result: FAILED, {failed} check(s) failed")
    raise SystemExit(0 if result["ok"] else 1)


def command_run(args: argparse.Namespace) -> None:
    """Offline proof, or a scored run: the main entry point for --model/--enforcement."""
    if bool(args.model) != bool(args.enforcement):
        raise SystemExit("--model and --enforcement must be given together")
    if args.resume and not args.model:
        raise SystemExit("--resume needs the --model and --enforcement of the interrupted run")

    run_command.ensure_public_catalog()
    run_command.demo_sample()

    if not args.model:
        print()
        print(
            "offline check passed. Add --model MODEL --enforcement ENFORCEMENT "
            "for a scored evaluation."
        )
        return

    enforcement, alias = run_command.resolve_enforcement_arg(args.enforcement)
    if args.resume:
        run_command.prepare_resume(args.resume)
    run_command.print_spend_estimate(args.full)
    signing_key_path = run_command.preflight(
        enforcement=enforcement,
        signing_key=args.signing_key,
        model=args.model,
        skip_model_preflight=args.skip_model_preflight,
    )

    calibration_report = None
    judge_model = None
    if args.full:
        judge_model = args.judge_model or os.environ.get(
            "ACCESSBENCH_JUDGE_MODEL", args.model
        )
        print(f"calibrating Anti-Cheat Judge ({judge_model}) before the run ...")
        calibration_report = run_command.ensure_judge_calibrated_for_run(
            judge_model, force=args.recalibrate
        )
        print(
            f"calibration: {calibration_report['gate']}, precision "
            f"{calibration_report.get('precision')} on "
            f"{calibration_report.get('n')} fixtures"
        )

    raws_before = run_command.snapshot_raws()
    results_before = run_command.snapshot_results()
    try:
        raw_path = run_command.run_eval_arm(args.model, enforcement, args.full)
    except BaseException:
        left_behind = run_command.resume_candidate(raws_before, args.resume)
        if left_behind is not None and left_behind.exists():
            print()
            print("the run stopped before finishing; raw evidence is retained. Resume with:")
            print("  " + run_command.resume_command(
                args.model, args.enforcement, args.full, left_behind
            ))
        raise
    print(f"raw evidence: {raw_path}")
    if args.full:
        run_command.check_signing_key_trust(signing_key_path)
        print(
            f"running Anti-Cheat Judge ({judge_model}) over a stratified "
            f"sample of up to {args.judge_sample_target} episodes ..."
        )
        sidecar_path = run_command.run_integrity_audit(
            raw_path,
            judge_model,
            judge_sample_target=args.judge_sample_target,
            calibration_report=calibration_report,
        )
        print(f"integrity sidecar: {sidecar_path}")
    results_root = run_command.aggregate_raw(raw_path)
    result_dir = run_command.find_new_result_dir(results_before, raw_path)
    bundle = run_command.build_bundle(
        result_dir,
        raw_path,
        argv=list(sys.argv),
        enforcement=enforcement,
        enforcement_alias=alias,
    )
    dashboard_cmd, dashboard_url = run_command.dashboard_hint()
    print()
    if args.full:
        print("full 600-case protocol, one pass per arm")
    else:
        print(SMOKE_WARNING)
        print("rerun with --full for the real protocol (600 cases, one pass per arm).")
    print(f"results written under {results_root}")
    print(f"result bundle: {bundle['bundle']}")
    print(f"  report:  {bundle['report']}")
    print(f"verify it: accessbench verify {bundle['bundle']}")
    print(f"view it:   {dashboard_cmd}  (then open {dashboard_url})")


def command_verify(args: argparse.Namespace) -> None:
    """Re-check one result directory from its retained raw evidence."""
    code = verify_result_module.main(args.result_dir, raw=args.raw, as_json=args.json)
    if code:
        raise SystemExit(code)


def command_trust_add_key(args: argparse.Namespace) -> None:
    """Admit a key to TRUSTED_KEYS.json. A deliberate, reviewed, git-recorded
    act; nothing in a normal run does this automatically."""
    import datetime as dt

    trust_registry.add_key(
        args.key_id,
        args.purpose,
        owner=args.owner,
        note=args.note or "",
        added_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    print(f"admitted {args.key_id} for {', '.join(args.purpose)}")
    print(f"commit {trust_registry.DEFAULT_REGISTRY_PATH} to make this trust take effect for others.")


def command_trust_list(args: argparse.Namespace) -> None:
    """List every key in TRUSTED_KEYS.json."""
    keys = trust_registry.list_keys()
    if not keys:
        print("TRUSTED_KEYS.json has no admitted keys yet.")
        return
    print(json.dumps(keys, indent=2, sort_keys=True))


def command_conformance(args: argparse.Namespace) -> None:
    from .conformance import run_conformance

    report = run_conformance(
        args.enforcement,
        timeout=args.timeout,
        bearer_token=os.environ.get("ACCESSBENCH_ENFORCEMENT_BEARER_TOKEN") or None,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise SystemExit("enforcement input did not pass conformance")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="accessbench",
        description=(
            "AccessBench: measure whether an agent leaks protected data with and "
            "without an enforcement layer in front of it. Start with `demo` "
            "(free, offline), then `run` (a scored run), then `verify` (re-check "
            "a result from its retained evidence). The remaining commands "
            "generate and validate the catalog; they never call a model API."
        ),
    )
    sub = ap.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        description="Run COMMAND --help for command-specific options.",
    )


    demo = sub.add_parser(
        "demo",
        help="free and offline: replay a few cases through the grader, no model needed",
        description=(
            "Run the first N catalog cases through the reference plan and print "
            "their exact-match, copy-tracking, task-success, and refusal results. "
            "This proves the grader works on this machine at zero cost; it is not "
            "a benchmark result."
        ),
    )
    demo.add_argument(
        "--catalog",
        default=str(run_command.CORE_CATALOG),
        help="catalog JSONL path (default: catalog/core_v2.jsonl)",
    )
    demo.add_argument(
        "--limit",
        type=int,
        default=run_command.DEFAULT_DEMO_LIMIT,
        help="number of cases to replay (default: %(default)s)",
    )
    demo.set_defaults(func=command_demo)

    run = sub.add_parser(
        "run",
        help="the main entry point: offline proof, or a scored run against a model and enforcement input",
        description=(
            "With no --model/--enforcement: generate the public catalog if "
            "missing and replay a demo sample, free and offline. With both: "
            "run one preflight (signing key, credentials, disk, PDP "
            "conformance, model tool use), then run in smoke mode by default "
            "(--full for the real 600-case protocol). A --full run first "
            "calibrates the Anti-Cheat Judge (cached after the first pass for "
            "a given judge model), then runs it over a stratified sample of "
            "episodes and writes the signed integrity sidecar aggregation "
            "needs. Every run ends with a self-contained results/<run_id>/ "
            "bundle (evidence/, run.json, report.html, VERIFY.txt) and the "
            "exact `accessbench verify` command."
        ),
    )
    run.add_argument("--model", help="subject model ID")
    run.add_argument(
        "--enforcement",
        help=(
            "`benchmark` (the Benchmark PDP, reference decision point), another "
            "built-in enforcement ID, or an AuthZEN server URL"
        ),
    )
    run.add_argument(
        "--full",
        action="store_true",
        help="run the full 600-case protocol instead of a smoke sample",
    )
    run.add_argument(
        "--resume",
        metavar="RAW_PATH",
        help=(
            "continue an interrupted run from its retained raw .jsonl (the path "
            "the interrupted run printed); --model, --enforcement and --full must match"
        ),
    )
    run.add_argument(
        "--skip-model-preflight",
        action="store_true",
        help=(
            "skip the one tiny tool-call request that proves the endpoint returns "
            "structured tool calls (only if you have already proven it)"
        ),
    )
    run.add_argument(
        "--signing-key",
        help="evidence-signing key path (default: auto-provisioned)",
    )
    run.add_argument(
        "--judge-model",
        help=(
            "Anti-Cheat Judge model ID, used only with --full (default: "
            "ACCESSBENCH_JUDGE_MODEL, else the subject --model)"
        ),
    )
    run.add_argument(
        "--judge-sample-target",
        type=int,
        default=run_command.DEFAULT_JUDGE_SAMPLE_TARGET,
        help=(
            "max episodes the Anti-Cheat Judge reviews per run, stratified "
            "by enforcer and mechanism (default: %(default)s; a run at or "
            "below this is reviewed in full)"
        ),
    )
    run.add_argument(
        "--recalibrate",
        action="store_true",
        help=(
            "ignore any cached Anti-Cheat Judge calibration for this judge "
            "model and re-run calibration before the --full run"
        ),
    )
    run.set_defaults(func=command_run)

    verify = sub.add_parser(
        "verify",
        help="re-check a result directory from its retained raw evidence",
        description=(
            "Check a results/<run_id>/ bundle: shape, raw digest, completeness, "
            "hash chain, signatures, an in-process recompute with aggregate.py, "
            "and the integrity sidecar. Exit 0 only if every check passes. For a "
            "legacy results directory without evidence/, pass --raw."
        ),
    )
    verify.add_argument("result_dir", help="results/<run_id>/ directory")
    verify.add_argument(
        "--raw",
        help="raw .jsonl path when the result directory has no evidence/ folder",
    )
    verify.add_argument("--json", action="store_true", help="machine-readable output")
    verify.set_defaults(func=command_verify)

    trust = sub.add_parser(
        "trust",
        help="manage TRUSTED_KEYS.json, the maintainer-controlled trusted-key registry",
        description=(
            "Admitting a key is a deliberate, reviewed act recorded in git "
            "history, not something a run does automatically. Nothing reads "
            "trust from a key until TRUSTED_KEYS.json (with that key in it) "
            "is committed."
        ),
    )
    trust_sub = trust.add_subparsers(dest="trust_command", required=True)

    trust_add = trust_sub.add_parser(
        "add-key", help="admit a key ID to the registry for one or more purposes",
    )
    trust_add.add_argument("--key-id", required=True, help="64-char hex SHA-256 key ID")
    trust_add.add_argument(
        "--purpose", required=True, action="append",
        choices=sorted(trust_registry.KNOWN_PURPOSES),
        help="repeat for multiple purposes",
    )
    trust_add.add_argument("--owner", required=True, help="who controls this key")
    trust_add.add_argument("--note", help="optional free-text context")
    trust_add.set_defaults(func=command_trust_add_key)

    trust_list = trust_sub.add_parser("list", help="list every registered key")
    trust_list.set_defaults(func=command_trust_list)

    attest = sub.add_parser(
        "attest-review",
        help="sign a record that you reviewed this exact 600-prompt development bank",
        description=(
            "Writes a signed record binding the bank's prompt-set, trial-id and "
            "catalog digests to a named reviewer, a decision and a date. Each "
            "reviewer signs their own record with their own key. This records "
            "maintainer review; it is not independent validation."
        ),
    )
    attest.add_argument("--reviewer", required=True, help="the reviewer's name as it should appear in the record")
    attest.add_argument("--decision", required=True, choices=review_attestation.DECISIONS)
    attest.add_argument("--exception", action="append", metavar="CASE_ID", help="a case id excepted from the decision; repeatable")
    attest.add_argument("--role", default="maintainer", help="the reviewer's relation to the project (default maintainer)")
    attest.add_argument("--date", default=dt.date.today().isoformat(), help="ISO date of the decision (default today)")
    attest.add_argument("--note", help="optional free text")
    attest.add_argument("--catalog", default=str(review_attestation.DEFAULT_CATALOG))
    attest.add_argument("--manifest", default=str(review_attestation.DEFAULT_MANIFEST), help="recorded bank manifest the catalog must match")
    attest.add_argument("--signing-key", help="Ed25519 private key PEM (default ACCESSBENCH_SIGNING_KEY or ~/.accessbench/signing-key.pem)")
    attest.add_argument("--out-dir", default=str(review_attestation.DEFAULT_OUT_DIR))
    attest.set_defaults(func=command_attest_review)

    vreview = sub.add_parser(
        "verify-review",
        help="check a bank review record: shape, signature, digest binding, fields",
    )
    vreview.add_argument("record", help="path to a review record written by attest-review")
    vreview.add_argument("--catalog", default=str(review_attestation.DEFAULT_CATALOG))
    vreview.add_argument("--manifest", default=str(review_attestation.DEFAULT_MANIFEST))
    vreview.add_argument("--json", action="store_true", help="machine-readable output")
    vreview.set_defaults(func=command_verify_review)

    conf = sub.add_parser(
        "conformance",
        help="check an AuthZEN enforcement endpoint before a run",
        description=(
            "Send synthetic event views (never scored-bank content) to an AuthZEN "
            "endpoint and report contract conformance: shape, reachability, boolean "
            "decision, implementation identity, state scope, rewrite shape, "
            "determinism, an advisory egress probe, and latency."
        ),
    )
    conf.add_argument("--enforcement", required=True, help="AuthZEN server root or evaluation URL")
    conf.add_argument("--timeout", type=float, default=15.0, help="per-request timeout seconds")
    conf.set_defaults(func=command_conformance)

    gen = sub.add_parser(
        "generate",
        help="generate and validate a public or held-out catalog",
        description=(
            "Generate one catalog split, validate every trial through deterministic "
            "reference replay, and write JSONL output. Held-out generation writes "
            "a mode-0600 local validation file, not an encrypted sealed pack."
        ),
    )
    gen.add_argument(
        "--split",
        choices=("public", "heldout"),
        default="public",
        help="catalog split to generate (default: public)",
    )
    gen.add_argument("--out", required=True, help="JSONL output path")
    gen.add_argument(
        "--seed-file",
        help="mode-0600 local seed file required for held-out generation",
    )
    gen.add_argument(
        "--phrase-bank",
        help="mode-0600 local JSON phrase bank for disjoint held-out wording",
    )
    gen.set_defaults(func=command_generate)

    val = sub.add_parser(
        "validate",
        help="validate one full construction matrix and replay expectations",
        description=(
            "Check a full generation matrix for IDs, coverage, hidden policy "
            "cases, app actions, data separation, and deterministic reference "
            "results. Use validate-core for the admitted 600-case subset."
        ),
    )
    val.add_argument("--catalog", required=True, help="catalog JSONL path")
    val.set_defaults(func=command_validate)

    core = sub.add_parser(
        "validate-core",
        help="validate the fixed core panel against its source matrix",
        description=(
            "Validate the full construction matrix, rebuild the fixed 600-case "
            "panel, and require an exact ordered match with the admitted catalog."
        ),
    )
    core.add_argument("--catalog", required=True, help="admitted core JSONL path")
    core.add_argument(
        "--source", required=True, help="full validated construction-matrix JSONL"
    )
    core.set_defaults(func=command_validate_core)

    comp = sub.add_parser(
        "compare-splits",
        help="check public and held-out split separation",
        description=(
            "Require different prompts, world IDs, and seed commitments while "
            "preserving identical structural coverage."
        ),
    )
    comp.add_argument("--public", required=True, help="public catalog JSONL path")
    comp.add_argument(
        "--heldout",
        required=True,
        help="local held-out catalog JSONL path",
    )
    comp.set_defaults(func=command_compare)

    man = sub.add_parser(
        "manifest",
        help="write public counts and digests for both catalog splits",
        description=(
            "Compare both splits and write a contamination manifest. The output "
            "contains held-out counts and digests, never held-out content."
        ),
    )
    man.add_argument("--public", required=True, help="public catalog JSONL path")
    man.add_argument(
        "--heldout",
        required=True,
        help="local held-out catalog JSONL path",
    )
    man.add_argument("--out", required=True, help="manifest JSON output path")
    man.set_defaults(func=command_manifest)

    signing_key = sub.add_parser(
        "generate-signing-key",
        help="create a mode-0600 evaluator evidence-signing key",
        description=(
            "Create an Ed25519 evaluator infrastructure key without overwriting "
            "an existing file. This is administrative setup, not a benchmark input."
        ),
    )
    signing_key.add_argument(
        "--out",
        required=True,
        help="new private-key path outside the result directory",
    )
    signing_key.set_defaults(func=command_generate_signing_key)
    return ap


def main() -> None:
    args = parser().parse_args()
    args.func(args)
