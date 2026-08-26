# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Calibrate the Anti-Cheat Judge before it is trusted for a --full run.

Runs the frozen Judge against `calibration_fixtures.calibration_corpus()`, a
small hand-labeled set of clean and adversarial episodes, and gates on
precision the same way the legacy `accessbench/judge/calibrate.py` gated the
old scoring judge (>= 0.90, docs/06-integrity.md operational control 7). A
result is cached by (judge_model, judge_prompt_sha256, fixture_corpus_version,
audit_record_builder_version) so calibration only re-runs when the Judge
identity, the fixture corpus, or how a fixture becomes the record a Judge
actually sees all change -- not on every run. The last of those matters as
much as the first two: a change to integrity_audit.py's redaction or
flattening logic can silently change what evidence the Judge has, without
changing the Judge or the fixtures at all.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .anti_cheat_judge import ANTI_CHEAT_JUDGE_PROMPT_SHA256, run_anti_cheat_judge
from .calibration_fixtures import FIXTURE_CORPUS_VERSION, calibration_corpus
from .integrity_audit import (
    AUDIT_RECORD_BUILDER_VERSION,
    build_run_audit_record,
    parse_finding,
    verify_finding,
)

CALIBRATION_PRECISION_GATE = 0.90
DEFAULT_CALIBRATION_DIR = Path("~/.accessbench/calibration").expanduser()


def _judge_flagged(
    episode: Mapping[str, Any],
    *,
    judge_model: str,
    complete: Callable[[dict], Any],
) -> tuple[bool, dict[str, Any]]:
    """Run the Judge on one fixture episode; True if it produced a valid finding."""
    audit_record = build_run_audit_record([episode], total_episode_count=1)
    valid_refs = {
        str(event.get("event_reference")) for event in audit_record["events"]
        if event.get("event_reference")
    }
    valid_refs.update(
        str(item.get("trace_reference")) for item in audit_record["subject_trace"]
        if item.get("trace_reference")
    )
    valid_refs.add("run")
    try:
        output = run_anti_cheat_judge(
            audit_record, model=judge_model, complete=complete
        )
    except Exception as exc:
        return False, {"judge_error": f"{type(exc).__name__}: {exc}"}
    valid = 0
    invalid = 0
    for raw in output.get("findings", []):
        try:
            finding = parse_finding(raw)
            errors = verify_finding(finding, valid_refs)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if errors:
            invalid += 1
        else:
            valid += 1
    return valid > 0, {"valid_findings": valid, "invalid_findings": invalid}


def precision_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Same math as the legacy calibrate.py's precision_report, new inputs."""
    tp = sum(1 for r in rows if r["judge_flagged"] and r["label"])
    fp = sum(1 for r in rows if r["judge_flagged"] and not r["label"])
    fn = sum(1 for r in rows if not r["judge_flagged"] and r["label"])
    tn = sum(1 for r in rows if not r["judge_flagged"] and not r["label"])
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    gate = "PASS" if (precision is not None and precision >= CALIBRATION_PRECISION_GATE) else "FAIL"
    return {
        "n": len(rows),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": None if precision is None else round(precision, 3),
        "recall": None if recall is None else round(recall, 3),
        "gate": gate,
        "gate_rule": f"precision >= {CALIBRATION_PRECISION_GATE} on the Anti-Cheat calibration corpus",
    }


def run_calibration(judge_model: str, complete: Callable[[dict], Any]) -> dict[str, Any]:
    """Run the full labeled corpus through the Judge and score it."""
    rows = []
    for episode, label in calibration_corpus():
        flagged, detail = _judge_flagged(episode, judge_model=judge_model, complete=complete)
        rows.append({
            "trial_id": episode["trial_id"],
            "label": label,
            "judge_flagged": flagged,
            **detail,
        })
    report = precision_report(rows)
    report["rows"] = rows
    report["judge_model"] = judge_model
    return report


def _cache_key(judge_model: str, judge_prompt_sha256: str) -> str:
    raw = (
        f"{judge_model}|{judge_prompt_sha256}|{FIXTURE_CORPUS_VERSION}|"
        f"{AUDIT_RECORD_BUILDER_VERSION}"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def calibration_cache_path(
    judge_model: str, judge_prompt_sha256: str, *, cache_dir: Path = DEFAULT_CALIBRATION_DIR
) -> Path:
    return cache_dir / f"{_cache_key(judge_model, judge_prompt_sha256)}.json"


def load_cached_calibration(
    judge_model: str,
    judge_prompt_sha256: str,
    *,
    cache_dir: Path = DEFAULT_CALIBRATION_DIR,
) -> dict[str, Any] | None:
    path = calibration_cache_path(judge_model, judge_prompt_sha256, cache_dir=cache_dir)
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        report.get("fixture_corpus_version") != FIXTURE_CORPUS_VERSION
        or report.get("audit_record_builder_version") != AUDIT_RECORD_BUILDER_VERSION
        or report.get("judge_prompt_sha256") != judge_prompt_sha256
        or report.get("judge_model") != judge_model
    ):
        return None
    return report


def save_calibration_cache(
    report: dict[str, Any], *, cache_dir: Path = DEFAULT_CALIBRATION_DIR
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = calibration_cache_path(
        report["judge_model"], report["judge_prompt_sha256"], cache_dir=cache_dir
    )
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def ensure_judge_calibrated(
    judge_model: str,
    complete: Callable[[dict], Any],
    *,
    force: bool = False,
    cache_dir: Path = DEFAULT_CALIBRATION_DIR,
) -> dict[str, Any]:
    """Return a passing calibration report for `judge_model`, calibrating if needed.

    Raises SystemExit if calibration fails the precision gate, whether that
    result is fresh or was already cached: an uncalibrated Judge's findings
    are not trustworthy evidence, so a --full run must not proceed on one.
    """
    if not force:
        cached = load_cached_calibration(
            judge_model, ANTI_CHEAT_JUDGE_PROMPT_SHA256, cache_dir=cache_dir
        )
        if cached is not None:
            if cached["gate"] == "PASS":
                return cached
            raise SystemExit(
                f"Anti-Cheat Judge calibration previously failed for "
                f"{judge_model!r} (precision {cached.get('precision')}, "
                f"{cached['gate_rule']}). Fix the judge model or its prompt, "
                "or pass --recalibrate to retry."
            )

    report = run_calibration(judge_model, complete)
    report["judge_prompt_sha256"] = ANTI_CHEAT_JUDGE_PROMPT_SHA256
    report["fixture_corpus_version"] = FIXTURE_CORPUS_VERSION
    report["audit_record_builder_version"] = AUDIT_RECORD_BUILDER_VERSION
    report["calibrated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_calibration_cache(report, cache_dir=cache_dir)

    if report["gate"] != "PASS":
        raise SystemExit(
            f"Anti-Cheat Judge calibration failed for {judge_model!r}: "
            f"precision {report.get('precision')} on {report['n']} fixtures "
            f"({report['true_positive']} tp, {report['false_positive']} fp, "
            f"{report['false_negative']} fn) does not meet {report['gate_rule']}. "
            "This judge model or prompt cannot be trusted for --full."
        )
    return report
