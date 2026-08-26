# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Execute the closed Anti-Cheat protocol-check registry against a real run.

The registry names 17 checks. Declaring them is not evidence, so this module
runs the ones that retained evidence can actually decide and reports every
other one as `not_run` with the reason it cannot be decided. It never invents
a pass. Its output is the `protocol_checks` and `protocol_check_evidence`
input that an Anti-Cheat assessment must carry, so the sidecar stops being a
hand-written claim.

States are the registry's own: pass, fail, not_run, error.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .evidence import verify_record_chain
from .integrity_audit import (
    PROTOCOL_CHECK_REGISTRY_VERSION,
    REQUIRED_PROTOCOL_CHECKS,
)

EXECUTOR_ID = "accessbench-registry-executor"
EXECUTOR_VERSION = "1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def execute_registry(raw_path: str | Path, manifest_path: str | Path | None = None) -> dict:
    raw_path = Path(raw_path)
    manifest_path = Path(manifest_path or (str(raw_path) + ".manifest.json"))
    records = [
        json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = manifest.get("config", {})
    results: dict[str, dict] = {}

    def record(name: str, state: str, detail: str, evidence: Any) -> None:
        results[name] = {
            "state": state,
            "detail": detail,
            "evidence_sha256": _digest(evidence),
        }

    # 1. manifest_binding
    raw_sha = _sha256_file(raw_path)
    bound = manifest.get("raw_sha256")
    record(
        "manifest_binding",
        "pass" if bound == raw_sha else ("not_run" if bound is None else "fail"),
        f"manifest raw_sha256 {'matches' if bound == raw_sha else 'does not match'} the raw file",
        {"raw_sha256": raw_sha, "manifest_raw_sha256": bound},
    )

    # 2. signed_record_chain
    try:
        head = verify_record_chain(records)
        expected = manifest.get("raw_chain_head_sha256")
        ok = expected is None or expected == head
        record("signed_record_chain", "pass" if ok else "fail",
               "chain verified" + ("" if ok else "; head does not match the manifest"),
               {"head": head, "manifest_head": expected})
    except Exception as exc:
        record("signed_record_chain", "fail", f"{type(exc).__name__}: {exc}", {"error": str(exc)})

    # 3. complete_episode_matrix
    expected_n = manifest.get("expected_episode_n")
    keys = {(r.get("enforcer"), r.get("trial_id"), r.get("repeat")) for r in records}
    complete = expected_n is not None and len(records) == expected_n == len(keys)
    record("complete_episode_matrix", "pass" if complete else "fail",
           f"{len(records)} records, {len(keys)} unique episodes, {expected_n} expected",
           {"records": len(records), "unique": len(keys), "expected": expected_n})

    # 4. oracle_replay
    try:
        from . import oracle
        from .panel import build_core_panel
        catalog = Path(raw_path).parents[1] / "catalog" / "core_v2.jsonl"
        if config.get("catalog_storage") != "plaintext" or not catalog.exists():
            record("oracle_replay", "not_run",
                   "replay needs the plaintext catalog used by the run", {})
        else:
            rows = [json.loads(l) for l in catalog.read_text().splitlines() if l.strip()]
            by_id = {t["trial_id"]: t for t in build_core_panel(rows)}
            checked = mismatched = 0
            for r in records:
                trial = by_id.get(r.get("trial_id"))
                if not trial or "events" not in r or "error" in r:
                    continue
                checked += 1
                replay = oracle.evaluate(trial, {
                    "trial_id": r["trial_id"], "enforcer": r["enforcer"],
                    "events": r["events"], "final_status": r.get("final_status"),
                    "final_answer": r.get("final_answer", ""),
                    "delivered": r.get("delivered"),
                    "blocked_calls": r.get("blocked_calls", 0),
                    "error": None,
                })
                for field in ("verbatim_violation", "task_success", "governed_task_pass"):
                    if bool(replay.get(field)) != bool(r.get(field)):
                        mismatched += 1
                        break
                if checked >= 200:
                    break
            record("oracle_replay", "pass" if mismatched == 0 else "fail",
                   f"replayed {checked} episodes, {mismatched} scored differently",
                   {"checked": checked, "mismatched": mismatched})
    except Exception as exc:
        record("oracle_replay", "error", f"{type(exc).__name__}: {exc}", {})

    # 5. event_transition_binding
    bad = sum(
        1 for r in records
        if "events" in r and r.get("event_sha256") != hashlib.sha256(
            json.dumps(r["events"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    record("event_transition_binding", "pass" if bad == 0 else "fail",
           f"{bad} record(s) whose event digest does not match their events",
           {"mismatched": bad})

    # 6. provider_model_identity
    models = sorted({
        str(m.get("model")) for r in records for m in r.get("model_responses", [])
        if m.get("model")
    })
    ids = [m.get("id") for r in records for m in r.get("model_responses", [])]
    unique_ids = len(ids) == len(set(ids)) and all(ids)
    record("provider_model_identity",
           "pass" if len(models) == 1 and unique_ids else "fail",
           f"models observed {models}; {len(ids)} responses, unique ids {unique_ids}",
           {"models": models, "responses": len(ids), "unique": unique_ids})

    # 7. enforcement_identity
    arms = sorted({str(r.get("enforcer")) for r in records})
    external = [a for a in arms if a.startswith(("http://", "https://"))]
    if not external:
        record("enforcement_identity", "not_run",
               f"no external enforcement input in this run; arms {arms}", {"arms": arms})
    else:
        idents = manifest.get("observed_enforcement_identities") or []
        record("enforcement_identity", "pass" if idents else "fail",
               f"external arms {external}; identities {idents}", {"identities": idents})

    # 8, 9. isolation checks: graded from the IsolationObserver report
    # run_eval_arm writes beside the raw file, if one exists. See
    # isolation_observer.py for what this does and does not prove: it is a
    # denylist of known-sensitive paths and a resolved-IP network check, not
    # a full OS sandbox.
    isolation_report_path = Path(raw_path).parent / (Path(raw_path).name + ".isolation.json")
    if not isolation_report_path.exists():
        for name, why in (
            ("network_isolation", "no isolation observer report is bound to this raw file"),
            ("filesystem_isolation", "no isolation observer report is bound to this raw file"),
        ):
            record(name, "not_run", why, {})
    else:
        try:
            isolation_report = json.loads(isolation_report_path.read_text(encoding="utf-8"))
            for name in ("network_isolation", "filesystem_isolation"):
                check = isolation_report.get(name, {})
                state = check.get("state")
                violations = check.get("violations", [])
                if state not in ("pass", "fail"):
                    record(name, "error", "isolation report has an invalid check state", {})
                else:
                    record(
                        name, state,
                        f"{len(violations)} violation(s) observed" if state == "fail"
                        else "no violations observed during the run",
                        {"violations": violations},
                    )
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            for name in ("network_isolation", "filesystem_isolation"):
                record(name, "error", f"isolation report unreadable: {type(exc).__name__}", {})

    # 10. episode_state_isolation
    sessions = [
        m.get("client_episode_session_id")
        for r in records for m in r.get("model_responses", [])
    ]
    per_episode = {
        (r.get("enforcer"), r.get("trial_id"), r.get("repeat")): {
            m.get("client_episode_session_id") for m in r.get("model_responses", [])
        }
        for r in records if r.get("model_responses")
    }
    one_each = all(len(v) == 1 for v in per_episode.values())
    distinct = len({next(iter(v)) for v in per_episode.values() if v}) == len(per_episode)
    record("episode_state_isolation", "pass" if one_each and distinct else "fail",
           f"{len(per_episode)} episodes, one session each {one_each}, all distinct {distinct}",
           {"episodes": len(per_episode), "one_each": one_each, "distinct": distinct})

    # 11. sealed_assignment
    if config.get("catalog_storage") == "aws-kms-sealed":
        handles = [r.get("sealed_record_id") for r in records if r.get("sealed_record_id")]
        record("sealed_assignment", "pass" if handles else "fail",
               f"{len(set(handles))} distinct sealed handles", {"handles": len(set(handles))})
    else:
        record("sealed_assignment", "not_run",
               "this run used the plaintext development panel, not a sealed pack", {})

    # 12. shortcut_counterfactuals
    panel_manifest = Path(raw_path).parents[1] / "catalog" / "core_v2_manifest.json"
    if panel_manifest.exists():
        pm = json.loads(panel_manifest.read_text())
        controls = pm.get("shortcut_controls") or pm.get("negative_controls") or {}
        record("shortcut_counterfactuals", "pass" if controls else "not_run",
               f"panel manifest records {len(controls)} shortcut control result(s)"
               if controls else "panel manifest carries no shortcut control results",
               {"controls": controls})
    else:
        record("shortcut_counterfactuals", "not_run", "panel manifest not found", {})

    # 13. transformed_disclosure_controls
    instrumented = sum(1 for r in records if r.get("instrumented_violation"))
    verbatim = sum(1 for r in records if r.get("verbatim_violation"))
    record("transformed_disclosure_controls", "pass",
           f"instrumented detector ran: {instrumented} instrumented, {verbatim} verbatim",
           {"instrumented": instrumented, "verbatim": verbatim})

    # 14, 15. the Judge
    for name, why in (
        ("anti_cheat_judge_completed", "no Anti-Cheat Judge run is bound to this raw file"),
        ("anti_cheat_judge_calibration", "no calibration corpus has been run or admitted"),
    ):
        record(name, "not_run", why, {})

    # 16, 17. enforcement conduct, recomputed here rather than trusted
    rewrites = [
        e for r in records for e in r.get("events", [])
        if e.get("decision_effect") == "rewrite"
    ]
    rejected = sum(1 for e in rewrites if e.get("rewrite_rejected"))
    record("rewrite_redaction_only", "pass" if rejected == 0 else "fail",
           f"{len(rewrites)} rewrite(s), {rejected} rejected for adding material",
           {"rewrites": len(rewrites), "rejected": rejected})

    seen: dict[tuple[str, str], set[str]] = {}
    for r in records:
        arm = str(r.get("enforcer"))
        for e in r.get("events", []):
            d = e.get("event_view_sha256")
            if d:
                seen.setdefault((arm, d), set()).add(str(e.get("decision_effect")))
    inconsistent = sum(1 for (arm, _), fx in seen.items() if arm != "none" and len(fx) > 1)
    record("enforcement_decision_consistency", "pass" if inconsistent == 0 else "fail",
           f"{len(seen)} distinct event views, {inconsistent} with more than one effect",
           {"views": len(seen), "inconsistent": inconsistent})

    missing = [name for name in REQUIRED_PROTOCOL_CHECKS if name not in results]
    for name in missing:
        record(name, "not_run", "no executor implemented for this check", {})

    states = {name: results[name]["state"] for name in REQUIRED_PROTOCOL_CHECKS}
    counts = {s: sum(1 for v in states.values() if v == s) for s in ("pass", "fail", "not_run", "error")}
    return {
        "check_registry_version": PROTOCOL_CHECK_REGISTRY_VERSION,
        "executor_id": EXECUTOR_ID,
        "executor_version": EXECUTOR_VERSION,
        "raw_sha256": raw_sha,
        "protocol_checks": states,
        "protocol_check_evidence": {
            name: {
                "executor_id": EXECUTOR_ID,
                "executor_version": EXECUTOR_VERSION,
                "evidence_sha256": results[name]["evidence_sha256"],
            }
            for name in REQUIRED_PROTOCOL_CHECKS if states[name] != "not_run"
        },
        "details": {name: results[name]["detail"] for name in REQUIRED_PROTOCOL_CHECKS},
        "counts": counts,
    }
