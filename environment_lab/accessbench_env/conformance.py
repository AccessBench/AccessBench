# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""AuthZEN enforcement-input conformance check.

A vendor runs this against its policy decision point before a real run. It
sends a small fixed set of synthetic event views (nothing from the scored
bank) and reports pass or fail per check with a reason. It never scores
anything and it is not a benchmark input; it only answers "will this endpoint
survive the run?" so nobody discovers a contract problem 3,600 episodes in.

Checks:

1. endpoint_shape          http(s) URL, no embedded credentials, no query.
2. reachable               the evaluation endpoint answers a valid request.
3. boolean_decision        every response carries a boolean ``decision``.
4. context_object          ``context`` and ``context.accessbench`` are objects.
5. implementation_identity ``context.accessbench.implementation`` carries a
                           non-empty ``id`` and ``version`` (needed for the
                           run manifest's enforcement identity evidence).
6. state_scope_declared    ``context.accessbench.state_scope`` is ``none``,
                           ``episode``, or ``run``.
7. rewrite_shape           if a rewrite is returned, its payload is a string.
8. deterministic           the byte-identical event view sent twice returns
                           the same effect.
9. denies_obvious_egress   a restricted-labeled payload to an external
                           destination is not allowed. Advisory only.
10. latency                median decision latency; over budget is a warning.
"""
from __future__ import annotations

import copy
import statistics
import time
from typing import Any
from urllib.parse import urlparse

from .enforcers import HttpEnforcer
from .models import Decision

CONFORMANCE_VERSION = "accessbench-authzen-conformance-v1"
LATENCY_BUDGET_MS = 500.0


def _base_view(boundary: str, destination_zone: str, classification: str) -> dict[str, Any]:
    """A synthetic event view that shares no content with the scored bank."""
    return {
        "timestamp": 10_000,
        "boundary": boundary,
        "app": "conformance_app",
        "action": "conformance_action",
        "resource_id": "conformance-resource-1",
        "payload": "conformance payload with no protected value",
        "destination": {
            "app": "conformance_sink",
            "resource_id": "conformance-sink-1",
            "tenant_id": "tenant_conformance",
            "trust_zone": destination_zone,
            "audience": "conformance_audience",
        },
        "decision_context": {
            "subject": {
                "principal_id": "conformance_user",
                "principal_type": "human",
                "tenant_id": "tenant_conformance",
                "roles": ["conformance_role"],
                "groups": ["employees"],
                "attributes": {"department": "conformance"},
            },
            "requester": {
                "principal_id": "conformance_requester",
                "principal_type": "human",
                "tenant_id": "tenant_conformance",
                "roles": ["manager"],
                "groups": ["employees"],
                "attributes": {},
            },
            "actor_chain": ["conformance_user"],
            "credential": {
                "credential_id": "cred_conformance",
                "subject_id": "conformance_user",
                "actor_id": "conformance_user",
                "issuer": "https://idp.conformance.invalid",
                "audience": ["conformance_app"],
                "scopes": ["conformance_app:read"],
                "issued_at": 6_000,
                "expires_at": 13_600,
                "auth_time": 9_880,
                "amr": ["pwd", "mfa"],
                "aal": "aal2",
                "session_id": "session_conformance",
                "revocation_epoch": 1,
                "revoked_at": None,
            },
            "purpose": "conformance_purpose",
            "task_id": "conformance_task",
            "profile_id": "conformance_profile",
            "approval_receipts": [],
            "session": {
                "device_posture": "managed",
                "network_zone": "corporate",
                "risk_level": "low",
            },
        },
        "observed_labels": [
            {
                "occurrence_id": "conformance-occ-1",
                "classification": classification,
                "allowed_roles": ["conformance_role"],
                "allowed_purposes": ["conformance_purpose"],
                "allowed_audiences": ["conformance_audience"],
            }
        ],
    }


def run_conformance(
    endpoint: str,
    *,
    timeout: float = 15.0,
    bearer_token: str | None = None,
    latency_budget_ms: float = LATENCY_BUDGET_MS,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool | None, detail: str) -> None:
        checks[name] = {
            "state": "pass" if ok else ("advisory" if ok is None else "fail"),
            "detail": detail,
        }

    parsed = urlparse(endpoint)
    shape_ok = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    record(
        "endpoint_shape", shape_ok,
        "http(s) URL without credentials, query, or fragment"
        if shape_ok else "endpoint must be an http(s) URL with no credentials, query, or fragment",
    )
    report: dict[str, Any] = {
        "conformance_version": CONFORMANCE_VERSION,
        "endpoint": endpoint,
        "checks": checks,
        "latency_ms": {},
        "errors": [],
    }
    if not shape_ok:
        report["ok"] = False
        return report

    enforcer = HttpEnforcer(endpoint, timeout=timeout, bearer_token=bearer_token)
    latencies: list[float] = []

    def decide(view: dict[str, Any]) -> Decision:
        started = time.perf_counter()
        decision = enforcer.decide(copy.deepcopy(view))
        latencies.append((time.perf_counter() - started) * 1000.0)
        return decision

    probe = _base_view("model_context", "internal", "internal")
    first = decide(probe)
    reachable = not any("unreachable" in e for e in enforcer.errors)
    record(
        "reachable", reachable,
        "evaluation endpoint answered" if reachable else ("; ".join(enforcer.errors) or "no answer"),
    )
    if not reachable:
        report["ok"] = False
        report["errors"] = list(enforcer.errors)
        return report

    boolean_ok = not any("boolean decision" in e for e in enforcer.errors)
    record("boolean_decision", boolean_ok,
           "decision is boolean" if boolean_ok else "decision was not a JSON boolean")
    context_ok = not any("must be an object" in e for e in enforcer.errors)
    record("context_object", context_ok,
           "context is an object" if context_ok else "context or context.accessbench was not an object")

    extension = first.metadata.get("authzen_response_context", {}).get("accessbench", {})
    if not isinstance(extension, dict):
        extension = {}
    implementation = extension.get("implementation", {})
    if not isinstance(implementation, dict):
        implementation = {}
    ident_ok = bool(implementation.get("id")) and bool(implementation.get("version"))
    record(
        "implementation_identity", ident_ok,
        f"id={implementation.get('id')!r} version={implementation.get('version')!r}"
        if ident_ok else "context.accessbench.implementation must carry non-empty id and version",
    )
    state_scope = extension.get("state_scope")
    scope_ok = state_scope in {"none", "episode", "run"}
    record(
        "state_scope_declared", scope_ok,
        f"state_scope={state_scope!r}" if scope_ok
        else "context.accessbench.state_scope must be none, episode, or run",
    )

    egress = _base_view("tool_input", "internal", "internal")
    decide(egress)
    rewrite_ok = not any("rewrite extension" in e for e in enforcer.errors)
    record("rewrite_shape", rewrite_ok,
           "no malformed rewrite observed" if rewrite_ok else "rewrite returned without a string payload")

    contradiction = not any("contradicts itself" in e for e in enforcer.errors)
    record(
        "decision_consistency", contradiction,
        "boolean decision and extension effect agree" if contradiction
        else "; ".join(e for e in enforcer.errors if "contradicts itself" in e),
    )

    again = decide(probe)
    deterministic = again.effect == first.effect
    record(
        "deterministic", deterministic,
        f"identical view returned {first.effect!r} both times"
        if deterministic else f"identical view returned {first.effect!r} then {again.effect!r}",
    )

    leaky = _base_view("tool_input", "external", "restricted")
    leaky["observed_labels"][0]["allowed_audiences"] = ["internal_only"]
    third = decide(leaky)
    record(
        "denies_obvious_egress", True if third.effect == "deny" else None,
        f"restricted label to external destination returned {third.effect!r}"
        + ("" if third.effect == "deny" else " (advisory: most policies deny this)"),
    )

    median = statistics.median(latencies) if latencies else 0.0
    report["latency_ms"] = {
        "median": round(median, 2),
        "max": round(max(latencies), 2) if latencies else 0.0,
        "budget": latency_budget_ms,
        "within_budget": median <= latency_budget_ms,
    }
    record(
        "latency", True if median <= latency_budget_ms else None,
        f"median {median:.1f} ms"
        + ("" if median <= latency_budget_ms else f" over the {latency_budget_ms:.0f} ms budget (warning)"),
    )
    report["errors"] = list(enforcer.errors)
    report["ok"] = all(c["state"] != "fail" for c in checks.values())
    return report
