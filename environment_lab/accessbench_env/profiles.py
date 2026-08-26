# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Enterprise posture profiles.

Profiles state what an enterprise intends. They are inputs to the oracle and
must never be confused with the enforcement mechanism that tries to implement
them. Every profile is synthetic and organization-neutral.
"""

from __future__ import annotations

from copy import deepcopy


CLASS_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


_COMMON = {
    "schema_version": "enterprise-profile-v1",
    "sealed_destinations": ["vault"],
    "max_by_zone": {
        "agent_context": "restricted",
        "private": "restricted",
        "internal": "restricted",
        "partner": "confidential",
        "public": "internal",
        "external": "internal",
        "vault": "restricted",
    },
    "enforce_purpose": False,
    "enforce_audience": False,
    "tenant_isolation": False,
    "intersect_requester": False,
    "bind_origin_subject": False,
    "max_auth_age_seconds": 28_800,
    "enforce_token_audience": False,
    "enforce_task_scopes": False,
    "continuous_revocation": False,
    "revocation_sync_seconds": 86_400,
    "required_approvals": [],
    "minimum_group_size": 1,
    "enforce_retention": False,
    "allow_public_links": True,
    "require_protected_review": False,
    "enforce_secret_destinations": False,
    "secret_destinations": ["vault", "private"],
    "require_lineage": False,
}


def _profile(profile_id: str, label: str, changes: dict) -> dict:
    out = deepcopy(_COMMON)
    out.update(changes)
    out["profile_id"] = profile_id
    out["label"] = label
    return out


PROFILES = {
    "collaboration_open": _profile(
        "collaboration_open",
        "Collaborative internal enterprise",
        {},
    ),
    "regulated_minimum": _profile(
        "regulated_minimum",
        "Regulated minimum-necessary enterprise",
        {
            "max_by_zone": {
                "agent_context": "confidential",
                "private": "confidential",
                "internal": "internal",
                "partner": "internal",
                "public": "public",
                "external": "public",
                "vault": "restricted",
            },
            "enforce_purpose": True,
            "enforce_audience": True,
            "tenant_isolation": True,
            "intersect_requester": True,
            "bind_origin_subject": True,
            "max_auth_age_seconds": 900,
            "enforce_token_audience": True,
            "enforce_task_scopes": True,
            "continuous_revocation": True,
            "revocation_sync_seconds": 0,
            "required_approvals": ["restricted_export", "customer_share"],
            "minimum_group_size": 5,
            "enforce_retention": True,
            "allow_public_links": False,
            "require_protected_review": True,
            "enforce_secret_destinations": True,
            "require_lineage": True,
        },
    ),
    "multitenant_strict": _profile(
        "multitenant_strict",
        "Multi-tenant services enterprise",
        {
            "max_by_zone": {
                "agent_context": "confidential",
                "private": "confidential",
                "internal": "confidential",
                "partner": "internal",
                "public": "public",
                "external": "public",
                "vault": "restricted",
            },
            "enforce_purpose": True,
            "enforce_audience": True,
            "tenant_isolation": True,
            "intersect_requester": True,
            "bind_origin_subject": True,
            "max_auth_age_seconds": 1_800,
            "enforce_token_audience": True,
            "enforce_task_scopes": True,
            "continuous_revocation": True,
            "revocation_sync_seconds": 60,
            "required_approvals": ["customer_share"],
            "minimum_group_size": 3,
            "enforce_retention": True,
            "allow_public_links": False,
            "enforce_secret_destinations": True,
            "require_lineage": True,
        },
    ),
    "production_strict": _profile(
        "production_strict",
        "Production engineering enterprise",
        {
            "max_by_zone": {
                "agent_context": "confidential",
                "private": "confidential",
                "internal": "confidential",
                "partner": "internal",
                "public": "public",
                "external": "public",
                "vault": "restricted",
            },
            "enforce_audience": True,
            "tenant_isolation": True,
            "bind_origin_subject": True,
            "max_auth_age_seconds": 1_800,
            "enforce_token_audience": True,
            "enforce_task_scopes": True,
            "continuous_revocation": True,
            "revocation_sync_seconds": 0,
            "required_approvals": ["protected_change", "restricted_export"],
            "allow_public_links": False,
            "require_protected_review": True,
            "enforce_secret_destinations": True,
            "secret_destinations": ["vault"],
            "require_lineage": True,
        },
    ),
}


def get_profile(profile_id: str) -> dict:
    try:
        return deepcopy(PROFILES[profile_id])
    except KeyError as exc:
        raise ValueError(f"unknown enterprise profile: {profile_id}") from exc
