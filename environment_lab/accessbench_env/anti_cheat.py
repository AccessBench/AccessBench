# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Public contract for the AccessBench Anti-Cheat subsystem.

AccessBench Anti-Cheat is a hybrid benchmark-integrity assurance subsystem.
It combines deterministic validators and detection algorithms with the
AccessBench Anti-Cheat Judge, an LLM-as-a-Judge for run-integrity evaluation.
It never grades task correctness and never reads or changes a benchmark score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


ANTI_CHEAT_NAME = "AccessBench Anti-Cheat"
ANTI_CHEAT_SCHEMA_VERSION = "accessbench-anti-cheat-assessment-v1"
ANTI_CHEAT_CLASSIFICATION = "hybrid benchmark-integrity assurance subsystem"
ANTI_CHEAT_PROCEDURE = "multi-stage integrity decision procedure"
ANTI_CHEAT_JUDGE_NAME = "AccessBench Anti-Cheat Judge"
ANTI_CHEAT_JUDGE_CLASSIFICATION = "LLM-as-a-Judge for run-integrity evaluation"

VALID = "Valid"
FLAGGED = "Flagged"
INELIGIBLE = "Ineligible"
INTEGRITY_STATUSES = frozenset({VALID, FLAGGED, INELIGIBLE})

ANTI_CHEAT_AUTHORITY = {
    "task_correctness": "deterministic_oracle",
    "performance_score": "deterministic_oracle",
    "anti_cheat_judge": "run_integrity_only",
}


def _has_items(value: Any) -> bool:
    return bool(
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and value
    )


def derive_anti_cheat_decision(
    diagnostics: Mapping[str, Any],
) -> tuple[str, list[str]]:
    """Derive the official status and stable reason codes from diagnostics.

    Reason codes identify the class of integrity evidence at issue. Exact
    check names, finding IDs, and reviewer attestations remain in the evidence
    fields so model-controlled text never becomes a reason code.
    """

    ineligible_signals = (
        ("hard_failures", "AC_DETERMINISTIC_CHECK_FAILED"),
        ("unknown_checks", "AC_CHECK_REGISTRY_UNKNOWN_ENTRY"),
        ("invalid_check_states", "AC_CHECK_STATE_INVALID"),
        ("unknown_check_evidence", "AC_CHECK_EVIDENCE_UNKNOWN_ENTRY"),
        ("invalid_check_evidence", "AC_CHECK_EVIDENCE_INVALID"),
        ("confirmed_material_finding_ids", "AC_FINDING_CONFIRMED"),
    )
    flagged_signals = (
        ("missing_checks", "AC_REQUIRED_CHECK_MISSING"),
        ("pending_checks", "AC_REQUIRED_CHECK_NOT_RUN"),
        ("missing_check_evidence", "AC_CHECK_EVIDENCE_MISSING"),
        ("finding_errors", "AC_JUDGE_OUTPUT_INVALID"),
        ("resolution_errors", "AC_REVIEW_RESOLUTION_INVALID"),
        ("unresolved_material_finding_ids", "AC_FINDING_UNRESOLVED"),
    )

    reason_codes: list[str] = []
    ineligible = False
    for field_name, reason_code in ineligible_signals:
        if _has_items(diagnostics.get(field_name)):
            ineligible = True
            reason_codes.append(reason_code)

    judge_binding = diagnostics.get("anti_cheat_judge_binding")
    judge_binding_errors = diagnostics.get("anti_cheat_judge_binding_errors")
    if _has_items(judge_binding_errors):
        if isinstance(judge_binding, Mapping) and judge_binding:
            ineligible = True
            reason_codes.append("AC_JUDGE_BINDING_INVALID")
        else:
            reason_codes.append("AC_JUDGE_BINDING_MISSING")

    flagged = False
    for field_name, reason_code in flagged_signals:
        if _has_items(diagnostics.get(field_name)):
            flagged = True
            reason_codes.append(reason_code)
    if diagnostics.get("anti_cheat_judge_error"):
        flagged = True
        reason_codes.append("AC_JUDGE_EXECUTION_ERROR")
    if _has_items(judge_binding_errors) and not judge_binding:
        flagged = True

    if ineligible:
        status = INELIGIBLE
    elif flagged:
        status = FLAGGED
    else:
        status = VALID
        reason_codes.append("AC_VALIDATED")
    return status, reason_codes


def build_anti_cheat_evidence_index(
    diagnostics: Mapping[str, Any],
    *,
    audit_record_sha256: str,
) -> dict[str, Any]:
    """Build the pointable evidence index returned with every decision."""

    findings = diagnostics.get("valid_findings", [])
    resolutions = diagnostics.get("authenticated_resolutions", [])
    return {
        "audit_record_sha256": audit_record_sha256,
        "check_registry_version": diagnostics.get("check_registry_version"),
        "protocol_check_evidence": diagnostics.get(
            "protocol_check_evidence", {}
        ),
        "anti_cheat_judge_binding": diagnostics.get(
            "anti_cheat_judge_binding", {}
        ),
        "valid_finding_ids": [
            finding.get("finding_id")
            for finding in findings
            if isinstance(finding, Mapping)
        ],
        "authenticated_resolution_finding_ids": [
            resolution.get("payload", {}).get("finding_id")
            for resolution in resolutions
            if isinstance(resolution, Mapping)
            and isinstance(resolution.get("payload"), Mapping)
        ],
        "unresolved_material_finding_ids": diagnostics.get(
            "unresolved_material_finding_ids", []
        ),
        "confirmed_material_finding_ids": diagnostics.get(
            "confirmed_material_finding_ids", []
        ),
    }


def anti_cheat_contract_fields() -> dict[str, Any]:
    """Return the immutable identity and authority portion of the result."""

    return {
        "schema_version": ANTI_CHEAT_SCHEMA_VERSION,
        "subsystem": ANTI_CHEAT_NAME,
        "academic_classification": ANTI_CHEAT_CLASSIFICATION,
        "decision_procedure": ANTI_CHEAT_PROCEDURE,
        "authority": dict(ANTI_CHEAT_AUTHORITY),
        "judge": {
            "name": ANTI_CHEAT_JUDGE_NAME,
            "academic_classification": ANTI_CHEAT_JUDGE_CLASSIFICATION,
            "authority": "run_integrity_only",
        },
    }
