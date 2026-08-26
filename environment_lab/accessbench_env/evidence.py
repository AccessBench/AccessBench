# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Hash-chain and Ed25519 evidence primitives for AccessBench.

The private key is evaluator infrastructure, not a benchmark input. A signature
authenticates the holder of that key; publication additionally requires the key
ID to appear in an independently maintained trusted-key registry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


CHAIN_FIELDS = frozenset({
    "chain_index", "previous_record_sha256", "record_sha256",
})


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def chain_record(
    record: Mapping[str, Any],
    *,
    chain_index: int,
    previous_record_sha256: str | None,
) -> dict[str, Any]:
    """Bind one immutable record to its position and predecessor."""
    if any(field in record for field in CHAIN_FIELDS):
        raise ValueError("record already contains chain fields")
    chained = {
        **record,
        "chain_index": chain_index,
        "previous_record_sha256": previous_record_sha256,
    }
    chained["record_sha256"] = sha256_hex(canonical_json_bytes(chained))
    return chained


def verify_record_chain(records: Iterable[Mapping[str, Any]]) -> str | None:
    """Validate ordering, predecessor links, and record digests."""
    previous = None
    for expected_index, record in enumerate(records):
        if record.get("chain_index") != expected_index:
            raise ValueError("record chain index mismatch")
        if record.get("previous_record_sha256") != previous:
            raise ValueError("record chain predecessor mismatch")
        unsigned = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        expected = sha256_hex(canonical_json_bytes(unsigned))
        if record.get("record_sha256") != expected:
            raise ValueError("record chain digest mismatch")
        previous = expected
    return previous


def _ed25519_modules():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise RuntimeError(
            "signed evidence requires the production cryptography dependency"
        ) from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def generate_signing_key(path: str | Path) -> str:
    """Create a mode-0600 Ed25519 private key without overwriting a file."""
    serialization, Ed25519PrivateKey, _ = _ed25519_modules()
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(pem)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return public_key_id(private_key.public_key())


def load_signing_key(path: str | Path):
    serialization, Ed25519PrivateKey, _ = _ed25519_modules()
    target = Path(path).expanduser()
    mode = target.stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError("signing key must not be readable by group or others")
    private_key = serialization.load_pem_private_key(target.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("signing key must be Ed25519")
    return private_key


def _public_key_bytes(public_key: Any) -> bytes:
    serialization, _, _ = _ed25519_modules()
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def public_key_id(public_key: Any) -> str:
    return sha256_hex(_public_key_bytes(public_key))


def sign_attestation(payload: Mapping[str, Any], private_key: Any, *, purpose: str) -> dict:
    """Sign a purpose-bound canonical payload and embed its public key."""
    public_raw = _public_key_bytes(private_key.public_key())
    signed = canonical_json_bytes({"purpose": purpose, "payload": payload})
    return {
        "algorithm": "Ed25519",
        "purpose": purpose,
        "key_id": sha256_hex(public_raw),
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "payload_sha256": sha256_hex(canonical_json_bytes(payload)),
        "signature": base64.b64encode(private_key.sign(signed)).decode("ascii"),
    }


def verify_attestation(
    payload: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    purpose: str,
    trusted_key_ids: Iterable[str] | None = None,
) -> str:
    """Verify an attestation and optionally require an independently trusted key."""
    _, _, Ed25519PublicKey = _ed25519_modules()
    if attestation.get("algorithm") != "Ed25519":
        raise ValueError("unsupported attestation algorithm")
    if attestation.get("purpose") != purpose:
        raise ValueError("attestation purpose mismatch")
    public_raw = base64.b64decode(attestation.get("public_key", ""), validate=True)
    key_id = sha256_hex(public_raw)
    if attestation.get("key_id") != key_id:
        raise ValueError("attestation key ID mismatch")
    if trusted_key_ids is not None and key_id not in set(trusted_key_ids):
        raise ValueError("attestation key is not independently trusted")
    payload_sha = sha256_hex(canonical_json_bytes(payload))
    if attestation.get("payload_sha256") != payload_sha:
        raise ValueError("attestation payload digest mismatch")
    signature = base64.b64decode(attestation.get("signature", ""), validate=True)
    signed = canonical_json_bytes({"purpose": purpose, "payload": payload})
    Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, signed)
    return key_id
