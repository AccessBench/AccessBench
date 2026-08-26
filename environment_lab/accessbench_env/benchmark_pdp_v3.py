# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Benchmark PDP v3: explicit record policy and fail-closed input handling.

This revision preserves v2's record-grain redaction and constructive denials.
It adds two enforcement mechanics that are part of a deployable PDP contract:

1. A record may carry ``max_auth_age_seconds``. The PDP then requires a
   verifiable authentication time recent enough for that record, independent
   of the record's sensitivity label.
2. Structurally malformed event views are denied before policy evaluation.
   Missing classification remains a valid sparse-label condition, but an
   unknown classification or a claim with the wrong type is not treated as an
   unlabeled allow.

The implementation reasons only from the event view. It imports no construction
or grading modules and contains no case identifiers.
"""
from __future__ import annotations

from typing import Any

from .benchmark_pdp_v2 import (
    CLASS_ORDER,
    GRADED,
    BenchmarkPDPv2,
    _as_int,
)
from .models import Decision


_LABEL_LIST_FIELDS = (
    "allowed_roles",
    "allowed_purposes",
    "allowed_audiences",
    "tags",
)
_PROFILE_LIST_FIELDS = (
    "required_approvals",
    "sealed_destinations",
    "secret_destinations",
)
_PROFILE_BOOL_FIELDS = (
    "continuous_revocation",
    "enforce_audience",
    "enforce_purpose",
    "enforce_secret_destinations",
    "enforce_task_scopes",
    "enforce_token_audience",
    "require_lineage",
    "require_protected_review",
    "tenant_isolation",
)
_CREDENTIAL_TIME_FIELDS = (
    "auth_time",
    "expires_at",
    "issued_at",
    "revoked_at",
)


def _is_int_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _malformed_event(view: Any) -> str | None:
    """Return a closed-schema problem, while permitting absent labels."""
    if not isinstance(view, dict):
        return "event view is not an object"
    if view.get("boundary") not in GRADED:
        return "boundary is absent or unknown"
    for field in ("app", "action", "resource_id", "payload"):
        if not isinstance(view.get(field), str):
            return f"{field} must be a string"
    if not _is_int_or_none(view.get("timestamp")) or view.get("timestamp") is None:
        return "timestamp must be an integer"

    destination = view.get("destination")
    if not isinstance(destination, dict):
        return "destination must be an object"
    for field in ("trust_zone", "audience", "tenant_id"):
        if field in destination and not isinstance(destination[field], str):
            return f"destination.{field} must be a string"

    context = view.get("decision_context")
    if not isinstance(context, dict):
        return "decision_context must be an object"
    subject = context.get("subject")
    if not isinstance(subject, dict):
        return "decision_context.subject must be an object"
    if not isinstance(subject.get("roles", []), list):
        return "decision_context.subject.roles must be a list"
    for field in ("actor_chain", "approval_receipts"):
        if field in context and not isinstance(context[field], list):
            return f"decision_context.{field} must be a list"

    credential = context.get("credential", {})
    if not isinstance(credential, dict):
        return "decision_context.credential must be an object"
    for field in _CREDENTIAL_TIME_FIELDS:
        if field in credential and not _is_int_or_none(credential[field]):
            return f"credential.{field} must be an integer or null"
    for field in ("audience", "scopes"):
        if field in credential and not isinstance(credential[field], list):
            return f"credential.{field} must be a list"

    profile = context.get("enterprise_profile", {})
    if not isinstance(profile, dict):
        return "decision_context.enterprise_profile must be an object"
    if "max_by_zone" in profile and not isinstance(profile["max_by_zone"], dict):
        return "enterprise_profile.max_by_zone must be an object"
    if "max_auth_age_seconds" in profile and (
        not _is_int_or_none(profile["max_auth_age_seconds"])
        or profile["max_auth_age_seconds"] is None
        or profile["max_auth_age_seconds"] < 0
    ):
        return "enterprise_profile.max_auth_age_seconds must be non-negative"
    for field in _PROFILE_LIST_FIELDS:
        if field in profile and not isinstance(profile[field], list):
            return f"enterprise_profile.{field} must be a list"
    for field in _PROFILE_BOOL_FIELDS:
        if field in profile and not isinstance(profile[field], bool):
            return f"enterprise_profile.{field} must be a boolean"

    labels = view.get("observed_labels")
    if not isinstance(labels, list):
        return "observed_labels must be a list"
    for label in labels:
        if not isinstance(label, dict):
            return "every observed label must be an object"
        classification = label.get("classification")
        if classification is not None and (
            not isinstance(classification, str)
            or classification.lower() not in CLASS_ORDER
        ):
            return "classification is outside the fixed vocabulary"
        for field in _LABEL_LIST_FIELDS:
            if field in label and not isinstance(label[field], list):
                return f"label.{field} must be a list"
        for field in ("record_selector", "source_tenant", "requires_approval"):
            if field in label and not isinstance(label[field], str):
                return f"label.{field} must be a string"
        if "max_auth_age_seconds" in label and (
            not _is_int_or_none(label["max_auth_age_seconds"])
            or label["max_auth_age_seconds"] is None
            or label["max_auth_age_seconds"] < 0
        ):
            return "label.max_auth_age_seconds must be non-negative"
    return None


def _record_auth_is_stale(
    label: dict[str, Any], context: dict[str, Any], now: Any,
) -> bool:
    """Fail closed only when a record explicitly requires recent auth."""
    if "max_auth_age_seconds" not in label:
        return False
    max_age = _as_int(label.get("max_auth_age_seconds"))
    credential = context.get("credential") or {}
    auth_time = _as_int(credential.get("auth_time")) if isinstance(
        credential, dict
    ) else None
    now_i = _as_int(now)
    if max_age is None or auth_time is None or now_i is None:
        return True
    return auth_time > now_i or now_i - auth_time > max_age


class BenchmarkPDPv3(BenchmarkPDPv2):
    """Record-policy-aware reference PDP, stateful within one episode."""

    name = "benchmark_pdp_v3"
    state_scope = "episode"

    def _source_block_reason(
        self, label: dict[str, Any], ctx: dict[str, Any], zone: str,
        profile: dict[str, Any], stale: bool,
    ) -> str | None:
        if _record_auth_is_stale(label, ctx, self._event_timestamp):
            return "credential"
        return super()._source_block_reason(label, ctx, zone, profile, stale)

    def _egress_block_reason(
        self, label: dict[str, Any], ctx: dict[str, Any], dest: dict[str, Any],
        profile: dict[str, Any], stale: bool,
    ) -> str | None:
        if _record_auth_is_stale(label, ctx, self._event_timestamp):
            return "credential"
        return super()._egress_block_reason(label, ctx, dest, profile, stale)

    def decide(self, ev: dict[str, Any]) -> Decision:
        problem = _malformed_event(ev)
        boundary = ev.get("boundary") if isinstance(ev, dict) else "unknown"
        if problem:
            return self._deny(
                "scope",
                str(boundary or "unknown"),
                "submit a complete event view that conforms to the fixed schema",
            )
        self._event_timestamp = ev["timestamp"]
        return super().decide(ev)
