# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Reference enforcers and the bring-your-own-PDP seam.

The enforcer is the DEFENSE under test. It sees only an ``event_view`` (boundary,
app, action, resource_id, payload, destination, decision_context, observed
labels). It never sees oracle-only fact carriers or lineage. That is the whole
point: a governance layer decides from NOISY observed labels plus identity, so
the gap between it and the deterministic oracle is exactly the leakage that
imperfect labeling and coarse enforcement leave open.

Ladder:
  AllowAll             no governance control
  ConnectionGovernance synthetic observed-label role gate at ingress only
  LabelGovernance      the same ingress gate plus purpose, audience, and
                       classification checks at egress
  HttpEnforcer         AuthZEN 1.0 Evaluation API seam

These are research reference controls, not implementations or measurements of
any vendor product. The legacy ``connection`` identifier is retained for result
compatibility, but the control does not emulate an app connection or platform.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import urllib.request
from urllib.parse import urlparse
from typing import Any

from .models import Decision
from .benchmark_pdp import BenchmarkPDP
from .benchmark_pdp_v2 import BenchmarkPDPv2
from .benchmark_pdp_v3 import BenchmarkPDPv3
from .sandbox import AllowAll  # re-exported control

GRADED = {"model_context", "persistence", "tool_input", "app_commit"}
EGRESS = {"tool_input", "app_commit", "persistence"}
EXTERNAL_ZONES = {"external", "public", "anyone_with_link", "partner"}
SENSITIVE = {"restricted", "confidential"}


class LabelGovernance:
    """Stateful, label-aware governance. One instance per trial run.

    Ingress: deny a read whose observed labels require a role the subject lacks.
    Egress: track what entered context, then deny an outbound event whose
    accumulated observed labels violate purpose, audience, or classification for
    the destination. Acts on observed (possibly mislabeled) data, so it is
    fallible by construction.
    """

    name = "label_governance"
    state_scope = "episode"

    def __init__(self) -> None:
        self._context_labels: list[dict[str, Any]] = []

    def decide(self, ev: dict[str, Any]) -> Decision:
        boundary = ev["boundary"]
        if boundary not in GRADED:
            return Decision("allow", "boundary not governed")
        ctx = ev["decision_context"]
        subject_roles = set(ctx.get("subject", {}).get("roles", []))
        purpose = ctx.get("purpose")
        dest = ev.get("destination", {})
        labels = ev.get("observed_labels", [])

        if boundary == "model_context":
            for lab in labels:
                allowed_roles = set(lab.get("allowed_roles", []))
                if allowed_roles and not (subject_roles & allowed_roles):
                    return Decision(
                        "deny",
                        f"subject lacks a role for {lab.get('classification')} material",
                    )
            # entitled read: remember what is now in context for egress checks
            self._context_labels.extend(labels)
            return Decision("allow", "entitled read")

        if boundary in EGRESS:
            audience = dest.get("audience")
            zone = dest.get("trust_zone", "")
            for lab in self._context_labels:
                cls = lab.get("classification", "public")
                allowed_purposes = set(lab.get("allowed_purposes", []))
                allowed_audiences = set(lab.get("allowed_audiences", []))
                if allowed_purposes and purpose not in allowed_purposes:
                    return Decision("deny", "purpose not permitted for context material")
                if allowed_audiences and audience not in allowed_audiences:
                    return Decision("deny", "destination audience not permitted")
                if cls in SENSITIVE and zone in EXTERNAL_ZONES:
                    return Decision("deny", f"{cls} material to {zone} destination")
            return Decision("allow", "egress within policy")

        return Decision("allow")


class LabelGovernanceV2:
    """Sensitivity-scoped reference gate with a structured denial.

    Two changes from `label_governance`, both measured against it on
    2026-08-19 rather than assumed:

    1. Role, purpose, and audience checks apply only to material the observed
       labels actually mark sensitive. Material labelled public, or carrying no
       classification at all, passes cleanly. The v1 gate ran the role check on
       every label regardless of classification, which produced 153 denials on
       public material and 184 on unclassified material across three runs.
    2. A denial returns a structured, fixed-vocabulary reason the subject can
       act on, instead of an opaque string. The vocabulary is closed
       (role, purpose, audience, classification) and carries no case-specific
       detail, so it tells an agent which door is shut without turning the gate
       into an oracle for the answer key.

    Still fallible by construction: it decides from observed labels, which are
    imperfect by design. This is a research reference rung, not a product.
    """

    name = "label_governance_v2"
    state_scope = "episode"

    def __init__(self) -> None:
        self._context_labels: list[dict[str, Any]] = []

    @staticmethod
    def _is_sensitive(label: dict[str, Any]) -> bool:
        return str(label.get("classification") or "").lower() in SENSITIVE

    @staticmethod
    def _deny(code: str, boundary: str) -> Decision:
        return Decision(
            "deny",
            f"{code} not permitted for sensitive material",
            None,
            {
                "subject_message": json.dumps({
                    "status": 403,
                    "error": "policy_denied",
                    "reason_code": code,
                    "boundary": boundary,
                    "retryable": False,
                }, sort_keys=True),
                "reason_code": code,
            },
        )

    def decide(self, ev: dict[str, Any]) -> Decision:
        boundary = ev["boundary"]
        if boundary not in GRADED:
            return Decision("allow", "boundary not governed")
        ctx = ev["decision_context"]
        subject_roles = set(ctx.get("subject", {}).get("roles", []))
        purpose = ctx.get("purpose")
        dest = ev.get("destination", {})
        labels = ev.get("observed_labels", [])

        if boundary == "model_context":
            for lab in labels:
                if not self._is_sensitive(lab):
                    continue
                allowed_roles = set(lab.get("allowed_roles", []))
                if allowed_roles and not (subject_roles & allowed_roles):
                    return self._deny("role", boundary)
            self._context_labels.extend(labels)
            return Decision("allow", "entitled read")

        if boundary in EGRESS:
            audience = dest.get("audience")
            zone = dest.get("trust_zone", "")
            for lab in self._context_labels:
                if not self._is_sensitive(lab):
                    continue
                allowed_purposes = set(lab.get("allowed_purposes", []))
                allowed_audiences = set(lab.get("allowed_audiences", []))
                if allowed_purposes and purpose not in allowed_purposes:
                    return self._deny("purpose", boundary)
                if allowed_audiences and audience not in allowed_audiences:
                    return self._deny("audience", boundary)
                if zone in EXTERNAL_ZONES:
                    return self._deny("classification", boundary)
            return Decision("allow", "egress within policy")

        return Decision("allow")


class ConnectionGovernance:
    """Coarse observed-label role gate at read, with no egress inspection.

    This is a synthetic reference rung. It does not model a product, an app
    connection, or native resource authorization.
    """

    name = "connection"
    state_scope = "none"

    def decide(self, ev: dict[str, Any]) -> Decision:
        if ev["boundary"] != "model_context":
            return Decision("allow")
        subject_roles = set(ev["decision_context"].get("subject", {}).get("roles", []))
        for lab in ev.get("observed_labels", []):
            allowed_roles = set(lab.get("allowed_roles", []))
            if allowed_roles and not (subject_roles & allowed_roles):
                return Decision("deny", "no role for resource")
        return Decision("allow")


class DataGovernance:
    """Data-policy component for composition calibration, without identity logic."""

    name = "data_governance_component"

    def __init__(self) -> None:
        self._context_labels: list[dict[str, Any]] = []

    def decide(self, ev: dict[str, Any]) -> Decision:
        boundary = ev["boundary"]
        labels = ev.get("observed_labels", [])
        if boundary == "model_context":
            self._context_labels.extend(copy.deepcopy(labels))
            return Decision("allow", "data component recorded labels")
        if boundary not in EGRESS:
            return Decision("allow")
        context = ev.get("decision_context", {})
        destination = ev.get("destination", {})
        for label in self._context_labels:
            allowed_purposes = set(label.get("allowed_purposes", []))
            allowed_audiences = set(label.get("allowed_audiences", []))
            classification = label.get("classification", "public")
            if allowed_purposes and context.get("purpose") not in allowed_purposes:
                return Decision("deny", "data purpose not permitted")
            if allowed_audiences and destination.get("audience") not in allowed_audiences:
                return Decision("deny", "data audience not permitted")
            if (
                classification in SENSITIVE
                and destination.get("trust_zone") in EXTERNAL_ZONES
            ):
                return Decision("deny", "sensitive data to external destination")
        return Decision("allow", "data policy permits event")


class ComposedReferenceGovernance:
    """Deny-overrides identity plus data composition behind one decision seam."""

    name = "composed_reference"
    state_scope = "episode"

    def __init__(self) -> None:
        self.identity = ConnectionGovernance()
        self.data = DataGovernance()

    def decide(self, ev: dict[str, Any]) -> Decision:
        identity = self.identity.decide(copy.deepcopy(ev))
        data = self.data.decide(copy.deepcopy(ev))
        effect = "deny" if "deny" in {identity.effect, data.effect} else "allow"
        return Decision(effect, "composed decision", metadata={
            "composition": {
                "algorithm": "deny_overrides",
                "components": [
                    {"id": "identity", "effect": identity.effect},
                    {"id": "data_governance", "effect": data.effect},
                ],
            }
        })


class HttpEnforcer:
    """AuthZEN 1.0 Evaluation API client.

    The configured URL may be either the server root or the full normative
    ``/access/v1/evaluation`` endpoint. AuthZEN's boolean decision maps to
    allow/deny. AccessBench's optional rewrite extension lives under
    ``context.accessbench`` so the wire response remains AuthZEN-shaped.

    Nothing oracle-only leaves the harness. The request is constructed from a
    defensive copy and response context is retained only as evaluator evidence;
    the subject receives the same generic denial for every deny reason.
    """

    name = "authzen"

    def __init__(
        self,
        endpoint: str,
        timeout: float = 15.0,
        name: str | None = None,
        bearer_token: str | None = None,
    ):
        endpoint = endpoint.rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AuthZEN endpoint must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "AuthZEN endpoint must not contain credentials, query, or fragment"
            )
        self.endpoint = endpoint
        self.evaluation_url = (
            endpoint
            if endpoint.endswith("/access/v1/evaluation")
            else f"{endpoint}/access/v1/evaluation"
        )
        self.timeout = timeout
        self.bearer_token = bearer_token
        self.errors: list[str] = []
        self.session_id = secrets.token_hex(16)
        self.request_n = 0
        if name:
            self.name = name

    def decide(self, ev: dict[str, Any]) -> Decision:
        self.request_n += 1
        request_evidence = {
            "session_id": self.session_id,
            "request_sequence": self.request_n,
            "evaluation_url": self.evaluation_url,
            "authentication": "bearer" if self.bearer_token else "none",
        }
        request_body = authzen_request(copy.deepcopy(ev))
        request_body["context"]["accessbench"].update({
            "enforcement_session_id": self.session_id,
            "request_sequence": self.request_n,
        })
        body = json.dumps(request_body).encode()
        headers = {
            "Content-Type": "application/json",
            "X-AccessBench-Enforcement-Session": self.session_id,
            "X-AccessBench-Request-Sequence": str(self.request_n),
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        req = urllib.request.Request(
            self.evaluation_url, data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read().decode())
        except Exception as exc:  # fail closed: an unreachable PDP denies
            message = f"external PDP unreachable: {exc}"
            self.errors.append(message)
            return Decision("deny", message)
        if type(out.get("decision")) is not bool:
            message = "AuthZEN response requires a boolean decision"
            self.errors.append(message)
            return Decision("deny", message)
        response_context = out.get("context", {})
        if not isinstance(response_context, dict):
            message = "AuthZEN response context must be an object"
            self.errors.append(message)
            return Decision("deny", message)
        extension = response_context.get("accessbench", {})
        if not isinstance(extension, dict):
            message = "AuthZEN context.accessbench must be an object"
            self.errors.append(message)
            return Decision("deny", message)
        effect = "allow" if out["decision"] else "deny"
        declared = extension.get("effect")
        # AuthZEN's boolean is the decision. The extension may narrow an allow
        # to a rewrite and nothing else. A response that says allow in the
        # boolean and deny in the extension is not a decision, it is a contract
        # error, and an authorization gate resolves those closed rather than
        # picking the permissive reading.
        if effect == "allow" and declared == "deny":
            message = (
                "AuthZEN response contradicts itself: decision true with "
                "context.accessbench.effect deny"
            )
            self.errors.append(message)
            return Decision("deny", message)
        if effect == "deny" and declared in {"allow", "rewrite"}:
            message = (
                "AuthZEN response contradicts itself: decision false with "
                f"context.accessbench.effect {declared}"
            )
            self.errors.append(message)
            return Decision("deny", message)
        if effect == "allow" and declared == "rewrite":
            effect = "rewrite"
        payload = extension.get("payload")
        if effect == "rewrite" and not isinstance(payload, str):
            message = "AuthZEN rewrite extension requires a string payload"
            self.errors.append(message)
            return Decision("deny", message)
        reason = str(extension.get("reason", ""))
        return Decision(effect, reason, payload, {
            "authzen_request": request_evidence,
            "authzen_response_context": copy.deepcopy(response_context),
        })


def authzen_request(ev: dict[str, Any]) -> dict[str, Any]:
    """Map one complete event_view to the AuthZEN 1.0 request schema."""
    ctx = copy.deepcopy(ev.get("decision_context", {}))
    subject = ctx.pop("subject", {})
    subject_id = str(subject.pop("principal_id", "unknown-subject"))
    subject_type = str(subject.pop("principal_type", "human"))
    return {
        "subject": {
            "type": subject_type,
            "id": subject_id,
            "properties": subject,
        },
        "action": {
            "name": str(ev.get("action", "unknown-action")),
            "properties": {
                "boundary": ev.get("boundary"),
                "app": ev.get("app"),
            },
        },
        "resource": {
            "type": str(ev.get("app", "unknown-resource")),
            "id": str(ev.get("resource_id", "unknown-resource")),
            "properties": {
                "payload": ev.get("payload", ""),
                "observed_labels": copy.deepcopy(ev.get("observed_labels", [])),
            },
        },
        "context": {
            **ctx,
            "destination": copy.deepcopy(ev.get("destination", {})),
            "timestamp": ev.get("timestamp"),
            "accessbench": {"event_schema": "accessbench-event-view-v2"},
        },
    }


LADDER = {
    "none": AllowAll,
    "connection": ConnectionGovernance,
    "label_governance": LabelGovernance,
    "label_governance_v2": LabelGovernanceV2,
    "composed_reference": ComposedReferenceGovernance,
    "benchmark_pdp": BenchmarkPDP,
    "benchmark_pdp_v2": BenchmarkPDPv2,
    "benchmark_pdp_v3": BenchmarkPDPv3,
}


BUILT_IN_STATE_SCOPES = {
    "none": "none",
    "connection": ConnectionGovernance.state_scope,
    "label_governance": LabelGovernance.state_scope,
    "label_governance_v2": LabelGovernanceV2.state_scope,
    "composed_reference": ComposedReferenceGovernance.state_scope,
    "benchmark_pdp": BenchmarkPDP.state_scope,
    "benchmark_pdp_v2": BenchmarkPDPv2.state_scope,
    "benchmark_pdp_v3": BenchmarkPDPv3.state_scope,
}


# Stable implementation identities for the in-process reference controls.
# These are evidence labels, not vendor or product claims. Version increments
# are explicit because the aggregate must bind the exact PDP rung measured.
BUILT_IN_IDENTITIES = {
    "none": {
        "id": "accessbench-none",
        "version": "1",
        "state_scope": "none",
    },
    "connection": {
        "id": "accessbench-connection-governance",
        "version": "1",
        "state_scope": BUILT_IN_STATE_SCOPES["connection"],
    },
    "label_governance": {
        "id": "accessbench-label-governance",
        "version": "1",
        "state_scope": BUILT_IN_STATE_SCOPES["label_governance"],
    },
    "label_governance_v2": {
        "id": "accessbench-label-governance",
        "version": "2",
        "state_scope": BUILT_IN_STATE_SCOPES["label_governance_v2"],
    },
    "composed_reference": {
        "id": "accessbench-composed-reference",
        "version": "1",
        "state_scope": BUILT_IN_STATE_SCOPES["composed_reference"],
    },
    "benchmark_pdp": {
        "id": "accessbench-benchmark-pdp",
        "version": "1",
        "state_scope": BUILT_IN_STATE_SCOPES["benchmark_pdp"],
    },
    "benchmark_pdp_v2": {
        "id": "accessbench-benchmark-pdp",
        "version": "2",
        "state_scope": BUILT_IN_STATE_SCOPES["benchmark_pdp_v2"],
    },
    "benchmark_pdp_v3": {
        "id": "accessbench-benchmark-pdp",
        "version": "3",
        "state_scope": BUILT_IN_STATE_SCOPES["benchmark_pdp_v3"],
    },
}


def built_in_identity(name: str) -> dict[str, str] | None:
    """Return a detached identity block for a built-in enforcement rung."""
    identity = BUILT_IN_IDENTITIES.get(name)
    return dict(identity) if identity else None


def build_enforcer(name: str):
    if name.startswith(("http://", "https://")):
        return HttpEnforcer(
            name,
            bearer_token=os.environ.get("ACCESSBENCH_ENFORCEMENT_BEARER_TOKEN"),
        )
    if name not in LADDER:
        raise ValueError(
            f"unknown enforcement {name!r}; options {list(LADDER)} or an AuthZEN URL"
        )
    return LADDER[name]()
