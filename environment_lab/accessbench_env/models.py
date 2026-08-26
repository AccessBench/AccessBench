# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Typed records shared by the generator, sandbox, and oracle.

The package serializes trials as plain JSON. These dataclasses define the
contract without forcing an enforcement adapter to import benchmark internals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


BOUNDARIES = (
    "source_return_raw",
    "model_context",
    "persistence",
    "tool_input",
    "app_commit",
    "audit_log",
)


@dataclass(frozen=True)
class Principal:
    principal_id: str
    tenant_id: str
    roles: tuple[str, ...]
    groups: tuple[str, ...]
    attributes: dict[str, str]
    principal_type: str = "human"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Credential:
    credential_id: str
    subject_id: str
    actor_id: str
    issuer: str
    audience: tuple[str, ...]
    scopes: tuple[str, ...]
    issued_at: int
    expires_at: int
    auth_time: int
    auth_methods: tuple[str, ...]
    assurance: str
    session_id: str
    revocation_epoch: int = 0
    revoked_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    entity_id: str
    attribute: str
    carrier: str
    consequence: str
    linkability: str
    tenant_id: str
    data_subjects: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    allowed_audiences: tuple[str, ...]
    allowed_purposes: tuple[str, ...]
    allowed_zones: tuple[str, ...]
    tags: tuple[str, ...]
    policy_constraint: str
    constraint_stage: str
    classification_observed: str | None
    tags_observed: tuple[str, ...]
    retention_until: int | None = None
    group_size: int | None = None
    derived_from: tuple[str, ...] = ()
    requires_approval: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    fact_id: str
    app: str
    resource_id: str
    selector: str
    version: int
    representation: str
    source_tenant: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Resource:
    resource_id: str
    app: str
    kind: str
    tenant_id: str
    owner_id: str
    audience: str
    parent_id: str | None
    version: int
    content: str
    occurrence_ids: tuple[str, ...]
    native_policy: dict[str, Any] = field(default_factory=dict)
    untrusted_content: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Destination:
    app: str
    resource_id: str
    tenant_id: str
    trust_zone: str
    audience: str
    audience_groups: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Event:
    seq: int
    timestamp: int
    boundary: str
    app: str
    action: str
    resource_id: str
    payload: str
    lineage_fact_ids: tuple[str, ...]
    visible_fact_ids: tuple[str, ...]
    destination: dict[str, Any]
    decision_context: dict[str, Any]
    allowed: bool = True
    reason: str = ""
    attempted_payload: str = ""
    decision_effect: str = "allow"
    decision_metadata: dict[str, Any] = field(default_factory=dict)
    decision_elapsed_ms: float = 0.0
    event_view_sha256: str = ""
    rewrite_added_word_n: int = 0
    rewrite_rejected: bool = False
    subject_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    effect: str
    reason: str = ""
    payload: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def stable_dict(value: Any) -> Any:
    """Convert dataclass-heavy values into JSON-ready structures."""
    if hasattr(value, "to_dict"):
        return stable_dict(value.to_dict())
    if isinstance(value, dict):
        return {str(k): stable_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [stable_dict(v) for v in value]
    return value
