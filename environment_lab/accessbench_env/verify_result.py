# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""`accessbench verify <result-directory>`: re-check a result from retained raw evidence.

Every check reuses the real primitives: the hash chain and Ed25519 helpers in
`evidence.py`, and `aggregate.main()` itself for the recompute. Nothing here
recomputes a score with its own logic; the verifier only compares.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from .evidence import verify_attestation, verify_record_chain
from .trust_registry import trusted_key_ids_for
from .report_html import (
    BENCHMARK_PDP_FIRST_MENTION,
    CONTROL_ARM_LABEL,
    FULL_LINE,
    SMOKE_WARNING,
    enforced_arm_label,
    pct,
)

PRE_RUN_PURPOSE = "accessbench-pre-run-v1"
RESULT_PURPOSE = "accessbench-result-v1"
INTEGRITY_PURPOSE = "accessbench-anti-cheat-assessment-v1"
RECOMPUTE_METRICS = (
    "governed_task_pass",
    "violation_all_episodes",
    "refusal",
    "task_success",
)
SELF_SIGNED_NOTE = (
    "self-signed by the operator's key; proves post-run integrity, not operator honesty"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class _Report:
    def __init__(self, result_dir: Path):
        self.result_dir = result_dir
        self.checks: list[dict] = []
        self.numbers: dict = {}

    def add(self, check: str, status: str, reason: str) -> None:
        self.checks.append({"check": check, "status": status, "reason": reason})

    @property
    def ok(self) -> bool:
        return all(c["status"] != "FAIL" for c in self.checks)

    def as_dict(self) -> dict:
        return {
            "result_dir": str(self.result_dir),
            "ok": self.ok,
            "checks": self.checks,
            "numbers": self.numbers,
        }


def _locate_evidence(result_dir: Path, raw_override: Path | None, report: _Report):
    """Check (a): bundle shape. Returns (raw, manifest, sidecar) or (None, None, None)."""
    evidence = result_dir / "evidence"
    if evidence.is_dir():
        raws = sorted(p for p in evidence.glob("*.jsonl") if p.is_file())
        if len(raws) != 1:
            report.add(
                "bundle shape", "FAIL",
                f"evidence/ must hold exactly one raw .jsonl, found {len(raws)}",
            )
            return None, None, None
        raw = raws[0]
        manifest = Path(str(raw) + ".manifest.json")
        if not manifest.exists():
            report.add("bundle shape", "FAIL", f"evidence/ lacks {manifest.name}")
            return None, None, None
        report.add(
            "bundle shape", "PASS",
            f"summary.json present; evidence/ holds {raw.name} and its manifest",
        )
    elif raw_override is not None:
        raw = Path(raw_override).expanduser().resolve()
        manifest = Path(str(raw) + ".manifest.json")
        if not raw.exists() or not manifest.exists():
            report.add(
                "bundle shape", "FAIL",
                f"--raw {raw} or its .manifest.json does not exist",
            )
            return None, None, None
        report.add(
            "bundle shape", "PASS",
            f"summary.json present; legacy layout, raw evidence taken from --raw {raw}",
        )
    else:
        report.add(
            "bundle shape", "FAIL",
            "no evidence/ directory; pass --raw PATH to point at the retained raw .jsonl",
        )
        return None, None, None
    sidecar = Path(str(raw) + ".integrity.json")
    return raw, manifest, (sidecar if sidecar.exists() else None)


def _recompute(raw: Path, manifest: Path) -> dict:
    """Run aggregate.main() in-process into a temporary root; never write under results/."""
    from . import run_command

    run_command._ensure_eval_on_path()
    import aggregate as aggregate_module

    with tempfile.TemporaryDirectory(prefix="accessbench-verify-") as tmp:
        argv = [
            "aggregate.py", "--raw", str(raw), "--manifest", str(manifest),
            "--stamp", "00000000-000000", "--out-root", tmp,
        ]
        sink = io.StringIO()
        with run_command._argv(argv), contextlib.redirect_stdout(sink):
            aggregate_module.main()
        written = list(Path(tmp).glob("*/summary.json"))
        if len(written) != 1:
            raise RuntimeError("recompute produced no summary.json")
        return json.loads(written[0].read_text(encoding="utf-8"))


def verify_result(result_dir: str | os.PathLike, raw: str | os.PathLike | None = None) -> dict:
    result_dir = Path(result_dir).expanduser().resolve()
    report = _Report(result_dir)
    summary_path = result_dir / "summary.json"
    if not summary_path.exists():
        report.add("bundle shape", "FAIL", f"{summary_path} is missing")
        return report.as_dict()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    meta = summary.get("meta", {})
    report.numbers = _numbers(summary, summary_path)

    raw_path, manifest_path, sidecar_path = _locate_evidence(
        result_dir, Path(raw) if raw else None, report
    )
    if raw_path is None:
        return report.as_dict()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_sha = _sha256_file(raw_path)
    report.numbers["digests"] = {
        "summary.json": _sha256_file(summary_path),
        raw_path.name: raw_sha,
        manifest_path.name: _sha256_file(manifest_path),
    }

    # (b) raw digest
    problems = []
    if manifest.get("raw_sha256") != raw_sha:
        problems.append(f"manifest raw_sha256 {manifest.get('raw_sha256')} != {raw_sha}")
    if meta.get("raw_sha256") and meta.get("raw_sha256") != raw_sha:
        problems.append(f"summary.json meta raw_sha256 {meta.get('raw_sha256')} != {raw_sha}")
    if problems:
        report.add("raw sha256", "FAIL", "; ".join(problems))
    else:
        report.add("raw sha256", "PASS", f"raw sha256 {raw_sha[:16]}... matches manifest and summary.json")

    # (c) completeness and mode
    mode = manifest.get("config", {}).get("evaluation_mode")
    mode_text = (
        "core (full 600-case protocol)" if mode == "core"
        else f"{mode or 'unknown'} (smoke sample, not reportable)"
    )
    completed = manifest.get("completed_episode_n")
    expected = manifest.get("expected_episode_n")
    if manifest.get("status") == "complete" and completed == expected:
        report.add(
            "completeness", "PASS",
            f"manifest status complete, {completed}/{expected} episodes; evaluation_mode {mode_text}",
        )
    else:
        report.add(
            "completeness", "FAIL",
            f"manifest status {manifest.get('status')!r}, {completed}/{expected} episodes; "
            f"evaluation_mode {mode_text}",
        )

    # (d) hash chain
    records: list[dict] = []
    try:
        records = _read_jsonl(raw_path)
        head = verify_record_chain(records)
        if head != manifest.get("raw_chain_head_sha256"):
            report.add(
                "hash chain", "FAIL",
                f"chain verifies but head {head} != manifest raw_chain_head_sha256 "
                f"{manifest.get('raw_chain_head_sha256')}",
            )
        else:
            report.add("hash chain", "PASS", f"{len(records)} records chain to head {str(head)[:16]}...")
    except (ValueError, json.JSONDecodeError) as exc:
        report.add("hash chain", "FAIL", f"record chain does not verify: {exc}")

    # (e) signatures
    try:
        pre_key = verify_attestation(
            manifest["pre_run_attestation_payload"], manifest["pre_run_attestation"],
            purpose=PRE_RUN_PURPOSE,
        )
        result_payload = manifest["result_attestation_payload"]
        result_key = verify_attestation(
            result_payload, manifest["result_attestation"], purpose=RESULT_PURPOSE,
        )
        bound = (
            result_payload.get("raw_sha256") == manifest.get("raw_sha256")
            and result_payload.get("raw_chain_head_sha256") == manifest.get("raw_chain_head_sha256")
        )
        if pre_key != result_key:
            report.add("signatures", "FAIL", "pre-run and result attestations use different keys")
        elif not bound:
            report.add("signatures", "FAIL", "result attestation does not bind the manifest raw digest and chain head")
        else:
            report.add("signatures", "PASS", f"pre-run and result attestations verify under key {result_key[:16]}...")
            trusted = trusted_key_ids_for(
                PRE_RUN_PURPOSE, "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
            ) | trusted_key_ids_for(
                RESULT_PURPOSE, "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
            )
            report.add("signing key", "INFO", SELF_SIGNED_NOTE)
            if result_key in trusted:
                report.add(
                    "key registry", "INFO",
                    "key id is listed in TRUSTED_KEYS.json or ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS "
                    "(maintainer-controlled registry; a recorded admission, not independent validation)",
                )
    except Exception as exc:
        report.add("signatures", "FAIL", f"attestation does not verify: {type(exc).__name__}: {exc}")

    # (f) recompute
    try:
        recomputed = _recompute(raw_path, manifest_path)
        mismatches = []
        arms = set(summary.get("summary", {})) | set(recomputed.get("summary", {}))
        for arm in sorted(arms):
            have = summary.get("summary", {}).get(arm, {})
            want = recomputed.get("summary", {}).get(arm, {})
            for metric in RECOMPUTE_METRICS:
                h, w = have.get(metric, {}), want.get(metric, {})
                pair_have = (h.get("positive_n"), h.get("n"))
                pair_want = (w.get("positive_n"), w.get("n"))
                if pair_have != pair_want:
                    mismatches.append(f"{arm}.{metric} bundle {pair_have} vs recomputed {pair_want}")
        if mismatches:
            report.add("recompute", "FAIL", "; ".join(mismatches))
        else:
            report.add(
                "recompute", "PASS",
                f"aggregate.py recomputed from the raw matches summary.json on {len(RECOMPUTE_METRICS)} "
                f"metrics x {len(arms)} arms",
            )
    except BaseException as exc:  # aggregate exits via SystemExit on refusal
        report.add("recompute", "FAIL", f"aggregate.py refused or failed: {type(exc).__name__}: {exc}")

    # (g) integrity sidecar
    if sidecar_path is None:
        report.add("integrity sidecar", "INFO", "no .integrity.json sidecar beside the raw (accessbench run --full writes one; without it the result stays Ineligible for publication)")
    else:
        try:
            package = json.loads(sidecar_path.read_text(encoding="utf-8"))
            payload = package["attestation_payload"]
            verify_attestation(payload, package["attestation"], purpose=INTEGRITY_PURPOSE)
            if payload.get("raw_sha256") != raw_sha:
                report.add("integrity sidecar", "FAIL", "sidecar raw_sha256 does not match this raw")
            else:
                status = (payload.get("assessment") or {}).get("integrity_status")
                report.add("integrity sidecar", "PASS", f"sidecar attestation verifies and binds this raw; status {status}")
        except Exception as exc:
            report.add("integrity sidecar", "FAIL", f"sidecar does not verify: {type(exc).__name__}: {exc}")

    return report.as_dict()


def _numbers(summary: dict, summary_path: Path) -> dict:
    meta = summary.get("meta", {})
    blocks = summary.get("summary", {})
    enforcement = meta.get("enforcement_input") or next((a for a in blocks if a != "none"), None)
    arms = []
    for arm_id, block in blocks.items():
        label = CONTROL_ARM_LABEL if arm_id == "none" else enforced_arm_label(enforcement, first_mention=True)
        arms.append({
            "arm": arm_id,
            "label": label,
            "work_completed_safely": pct(block.get("governed_task_pass")),
            "protected_data_exfiltrated": pct(block.get("violation_all_episodes")),
            "refusal": pct(block.get("refusal")),
            "task_completed": pct(block.get("task_success")),
        })
    arms.sort(key=lambda a: a["arm"] != "none")
    integrity = meta.get("integrity") or {}
    return {
        "model": meta.get("model"),
        "evaluation_mode": meta.get("evaluation_mode"),
        "episodes_run": meta.get("episodes_run"),
        "case_n": meta.get("fixed_bank_case_n"),
        "publication_eligible": meta.get("publication_eligible"),
        "integrity_status": integrity.get("integrity_status"),
        "integrity_reason": integrity.get("reason"),
        "arms": arms,
    }


def format_report(result: dict) -> str:
    lines = [f"accessbench verify {result['result_dir']}"]
    for check in result["checks"]:
        lines.append(f"{check['status']:<4} {check['check']}: {check['reason']}")
    numbers = result.get("numbers") or {}
    if numbers.get("arms"):
        lines.append("")
        lines.append(f"numbers of record for {numbers.get('model')}")
        for arm in numbers["arms"]:
            lines.append(
                f"  {arm['label']}: work completed safely {arm['work_completed_safely']}; "
                f"protected data exfiltrated {arm['protected_data_exfiltrated']}; "
                f"refusal {arm['refusal']}; task completed {arm['task_completed']}"
            )
        mode = numbers.get("evaluation_mode")
        if mode == "core":
            lines.append(f"evaluation mode: core. {FULL_LINE}.")
        else:
            lines.append(
                f"evaluation mode: {mode or 'unknown'} ({numbers.get('case_n')} cases). "
                f"{SMOKE_WARNING}"
            )
        lines.append(
            f"publication: publication_eligible {json.dumps(numbers.get('publication_eligible'))}; "
            f"integrity status {numbers.get('integrity_status') or 'not recorded'}"
            + (f" ({numbers['integrity_reason']})" if numbers.get("integrity_reason") else "")
        )
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    lines.append("")
    lines.append(
        "result: VERIFIED, every check passed" if not fails
        else f"result: FAILED, {len(fails)} check(s) failed"
    )
    return "\n".join(lines)


def main(result_dir: str, raw: str | None = None, as_json: bool = False) -> int:
    result = verify_result(result_dir, raw)
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_report(result))
    return 0 if result["ok"] else 1


# Keep the first-mention wording importable for tests and docs.
__all__ = ["verify_result", "format_report", "main", "BENCHMARK_PDP_FIRST_MENTION"]
