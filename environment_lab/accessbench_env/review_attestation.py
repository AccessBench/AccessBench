# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Bank review attestation: a signed record that a named reviewer read this
exact 600-prompt development bank and reached a decision.

What it proves: the holder of the signing key, who names themselves in the
payload, attested on the given date to a decision about the prompt set whose
digests (prompt set, trial ids, catalog file) are bound in the payload; the
record detects later modification and binds to one exact bank. What it does
not prove: independent validation. The reviewers today are the maintainers,
so this is maintainer review, recorded and verifiable, nothing more.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .evidence import load_signing_key, sign_attestation, verify_attestation
from .panel import core_panel_manifest
from .validate import file_sha256, read_jsonl

RECORD_TYPE = "accessbench-bank-review-v1"
PURPOSE = "accessbench-bank-review-v1"
DECISIONS = ("accept", "accept-with-exceptions", "reject")
LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = LAB_ROOT / "catalog" / "core_v2.jsonl"
DEFAULT_MANIFEST = LAB_ROOT / "catalog" / "core_v2_manifest.json"
DEFAULT_OUT_DIR = LAB_ROOT.parent / "verification" / "review-attestations"
REVIEW_METHOD = (
    "paper review by a named maintainer; collaborator review, "
    "not independent validation"
)
BOUND_FIELDS = ("panel_id", "case_n", "prompt_set_sha256", "trial_ids_sha256", "catalog_sha256")
SELF_SIGNED_NOTE = (
    "signed by the reviewer's own key: it names the reviewer and binds the exact "
    "bank; it does not make the review independent"
)


def catalog_trial_ids(catalog: str | Path = DEFAULT_CATALOG) -> list[str]:
    return [row["trial_id"] for row in read_jsonl(str(catalog))]


def bank_digests(
    catalog: str | Path = DEFAULT_CATALOG,
    manifest: str | Path | None = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Recompute the bank's identity from the catalog and check it against the
    recorded manifest, so a record can never bind a bank that is not the one
    on disk."""
    catalog = Path(catalog)
    rows = read_jsonl(str(catalog))
    panel = core_panel_manifest(rows)
    digests = {
        "panel_id": panel["panel_id"],
        "panel_status": panel["panel_status"],
        "case_n": panel["case_n"],
        "prompt_set_sha256": panel.get("prompt_set_sha256"),
        "trial_ids_sha256": panel["trial_ids_sha256"],
        "catalog_sha256": file_sha256(str(catalog)),
    }
    if manifest is not None and Path(manifest).exists():
        recorded = json.loads(Path(manifest).read_text(encoding="utf-8"))
        for field in BOUND_FIELDS:
            if recorded.get(field) != digests[field]:
                raise ValueError(
                    f"catalog {field} {digests[field]} does not match the recorded "
                    f"manifest value {recorded.get(field)} in {manifest}"
                )
    return digests


def build_payload(
    digests: dict[str, Any],
    *,
    reviewer: str,
    decision: str,
    date: str,
    exceptions: Iterable[str] = (),
    role: str = "maintainer",
    note: str = "",
) -> dict[str, Any]:
    if not reviewer.strip():
        raise ValueError("reviewer name is required")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    exceptions = sorted({item.strip() for item in exceptions if item.strip()})
    if decision == "accept" and exceptions:
        raise ValueError("an accept decision cannot carry exceptions; use accept-with-exceptions")
    if decision == "accept-with-exceptions" and not exceptions:
        raise ValueError("accept-with-exceptions needs at least one --exception case id")
    dt.date.fromisoformat(date)  # raises on a malformed date
    payload = {"record_type": RECORD_TYPE}
    payload.update({field: digests[field] for field in BOUND_FIELDS})
    payload.update({
        "panel_status": digests.get("panel_status"),
        "reviewed_range": f"1-{digests['case_n']}",
        "reviewer": {"name": reviewer.strip(), "role": role},
        "decision": decision,
        "date": date,
        "exceptions": exceptions,
        "review_method": REVIEW_METHOD,
        "note": note,
    })
    return payload


def sign_review(payload: dict[str, Any], private_key: Any) -> dict[str, Any]:
    return {
        "record_type": RECORD_TYPE,
        "payload": payload,
        "attestation": sign_attestation(payload, private_key, purpose=PURPOSE),
    }


def record_filename(payload: dict[str, Any]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", payload["reviewer"]["name"].lower()).strip("-")
    return f"{slug or 'reviewer'}-{payload['date']}.json"


def write_review(record: dict[str, Any], out_dir: str | Path = DEFAULT_OUT_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / record_filename(record["payload"])
    if path.exists():
        raise FileExistsError(f"{path} already exists; remove it first to re-sign")
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_review(
    record: dict[str, Any],
    *,
    catalog: str | Path | None = DEFAULT_CATALOG,
    manifest: str | Path | None = DEFAULT_MANIFEST,
    trusted_key_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Verify shape, signature, digest binding and fields. PASS/FAIL per check;
    ok only when nothing failed."""
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    payload = record.get("payload")
    attestation = record.get("attestation")
    key_id = None
    if record.get("record_type") != RECORD_TYPE or not isinstance(payload, dict) or not isinstance(attestation, dict):
        add("shape", "FAIL", f"not a {RECORD_TYPE} record with payload and attestation")
        return {"ok": False, "checks": checks, "key_id": None}
    add("shape", "PASS", f"{RECORD_TYPE} record")
    try:
        key_id = verify_attestation(payload, attestation, purpose=PURPOSE)
        add("signature", "PASS", f"Ed25519 attestation verifies under key {key_id[:16]}...")
    except Exception as exc:
        add("signature", "FAIL", f"attestation does not verify: {type(exc).__name__}: {exc}")
    if catalog is not None:
        try:
            digests = bank_digests(catalog, manifest)
            mismatched = [f for f in BOUND_FIELDS if payload.get(f) != digests[f]]
            if mismatched:
                add("digest binding", "FAIL", "record does not bind the bank on disk: " + ", ".join(mismatched))
            else:
                add("digest binding", "PASS", f"binds {digests['panel_id']} prompt set {digests['prompt_set_sha256'][:16]}...")
        except Exception as exc:
            add("digest binding", "FAIL", f"could not recompute the bank digests: {type(exc).__name__}: {exc}")
    reviewer = payload.get("reviewer") or {}
    missing = [
        name for name, present in (
            ("reviewer.name", bool(isinstance(reviewer, dict) and reviewer.get("name"))),
            ("decision", payload.get("decision") in DECISIONS),
            ("date", bool(payload.get("date"))),
            ("reviewed_range", bool(payload.get("reviewed_range"))),
        ) if not present
    ]
    if missing:
        add("fields", "FAIL", "missing or invalid: " + ", ".join(missing))
    else:
        add("fields", "PASS", f"{reviewer.get('name')} ({reviewer.get('role')}), {payload['decision']}, {payload['date']}, {len(payload.get('exceptions') or [])} exception(s)")
    if key_id is not None:
        if trusted_key_ids is not None and key_id in set(trusted_key_ids):
            add("signing key", "INFO", "key is listed in the maintainer key registry; that is a recorded admission, not independence")
        else:
            add("signing key", "INFO", SELF_SIGNED_NOTE)
    ok = all(item["status"] != "FAIL" for item in checks)
    return {
        "ok": ok,
        "checks": checks,
        "key_id": key_id,
        "reviewer": reviewer.get("name") if isinstance(reviewer, dict) else None,
        "decision": payload.get("decision"),
        "date": payload.get("date"),
    }


def load_private_key(path: str | Path):
    return load_signing_key(path)
