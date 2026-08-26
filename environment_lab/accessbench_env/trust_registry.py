# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""The trusted-key registry: maintainer-controlled until an outside party holds
part of it. Listing a key is a recorded admission, never independent validation.

evidence.py's own docstring states the requirement this exists to satisfy: "a
signature authenticates the holder of that key; publication additionally
requires the key ID to appear in an independently maintained trusted-key
registry." A signature alone only proves key possession, not that anyone
other than the signer considers that key legitimate.

Before this module, "trust" was an environment variable set at run time by
whoever was running the benchmark -- self-attestation with a different name,
since nothing stopped an operator from trusting their own key on every run
with no record of having done so. This registry is a version-controlled file
(TRUSTED_KEYS.json at the repo root): adding a key is a deliberate, reviewed,
git-recorded act, separate from the runtime environment that produces a
result. That is what "independently maintained" and "external append-only
commitment" (docs/06-integrity.md) mean in a solo-maintainer project today:
process separation and a durable, clonable, tamper-evident history, not
proof of a second organization. A second real signer can be added to this
same registry later without changing how any of this code works.

The ACCESSBENCH_TRUSTED_*_KEY_IDS environment variables remain a supported
override on top of the registry (useful for CI and one-off runs), but the
registry file is the default, persistent source of trust.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA_VERSION = "accessbench-trusted-key-registry-v1"
KNOWN_PURPOSES = frozenset({
    "accessbench-anti-cheat-assessment-v1",
    "accessbench-bank-review-v1",
    "accessbench-human-resolution-v1",
    "accessbench-pre-run-v1",
    "accessbench-result-v1",
})
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "TRUSTED_KEYS.json"
PURPOSE_ENV_VARS = {
    "accessbench-anti-cheat-assessment-v1": "ACCESSBENCH_TRUSTED_ANTI_CHEAT_KEY_IDS",
    "accessbench-bank-review-v1": "ACCESSBENCH_TRUSTED_REVIEWER_KEY_IDS",
    "accessbench-human-resolution-v1": "ACCESSBENCH_TRUSTED_REVIEWER_KEY_IDS",
    "accessbench-pre-run-v1": "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
    "accessbench-result-v1": "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
}


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load the registry. A missing file is an empty registry, not an error:
    a fresh clone or a CI checkout has admitted no keys yet, which is a
    legitimate (if unhelpful) state, not a corruption to fail loudly on.
    """
    path = path if path is not None else DEFAULT_REGISTRY_PATH
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "keys": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported trusted-key registry schema_version "
            f"{data.get('schema_version')!r}"
        )
    return data


def save_registry(registry: dict[str, Any], path: Path | None = None) -> None:
    path = path if path is not None else DEFAULT_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "keys": sorted(registry.get("keys", []), key=lambda entry: entry["key_id"]),
    }
    path.write_text(
        json.dumps(ordered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def registry_trusted_key_ids(
    purpose: str, *, path: Path | None = None
) -> set[str]:
    """Key IDs in the registry admitted for exactly this purpose."""
    registry = load_registry(path)
    return {
        entry["key_id"]
        for entry in registry.get("keys", [])
        if purpose in entry.get("purposes", [])
    }


def trusted_key_ids_for(
    purpose: str,
    env_var: str,
    *,
    path: Path | None = None,
) -> set[str]:
    """The registry's trust for `purpose`, plus the env var override.

    The registry file is the default, persistent source; the env var is an
    additive override for CI and one-off runs, never a replacement for it.
    """
    ids = set(registry_trusted_key_ids(purpose, path=path))
    ids.update(
        item.strip() for item in os.environ.get(env_var, "").split(",") if item.strip()
    )
    return ids


def add_key(
    key_id: str,
    purposes: list[str],
    *,
    owner: str,
    note: str = "",
    added_at: str,
    path: Path | None = None,
) -> None:
    """Admit a key to the registry. Refuses silently overwriting an existing
    entry: re-registering the same key_id is either a mistake or a real
    change to what it's trusted for, and both deserve a human looking at the
    diff, not a merge this function guesses at.
    """
    if not _is_sha256(key_id):
        raise ValueError(f"key_id must be a 64-character hex SHA-256 digest, got {key_id!r}")
    if not purposes:
        raise ValueError("at least one purpose is required")
    unknown = sorted(set(purposes) - KNOWN_PURPOSES)
    if unknown:
        raise ValueError(
            f"unknown purpose(s) {unknown}; known purposes are {sorted(KNOWN_PURPOSES)}"
        )
    if not owner.strip():
        raise ValueError("owner is required")
    path = path if path is not None else DEFAULT_REGISTRY_PATH
    registry = load_registry(path)
    if any(entry["key_id"] == key_id for entry in registry["keys"]):
        raise ValueError(
            f"{key_id} is already registered; edit {path} directly to change "
            "its purposes or note"
        )
    registry["keys"].append({
        "key_id": key_id,
        "purposes": sorted(set(purposes)),
        "owner": owner,
        "added_at": added_at,
        "note": note,
    })
    save_registry(registry, path)


def list_keys(path: Path | None = None) -> list[dict[str, Any]]:
    return list(load_registry(path).get("keys", []))


def is_key_trusted(
    key_id: str, purpose: str, *, path: Path | None = None
) -> bool:
    env_var = PURPOSE_ENV_VARS[purpose]
    return key_id in trusted_key_ids_for(purpose, env_var, path=path)
