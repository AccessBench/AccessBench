# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Managed-KMS envelope encryption for private benchmark assets.

The on-disk format is a small authenticated JSON header, streamed AES-256-GCM
ciphertext, and the 16-byte GCM tag. AWS KMS wraps the one-time data key. KMS
encryption context values are deliberately non-secret because AWS logs them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import struct
import tempfile
from pathlib import Path
from typing import Any, Protocol


MAGIC = b"ABKMS1\n\x00"
CATALOG_MAGIC = b"ABPACK1\n"
TAG_BYTES = 16
MAX_HEADER_BYTES = 64 * 1024
MAX_INDEX_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
SCHEMA_VERSION = "accessbench-sealed-asset-v1"
CATALOG_RECORD_PLAINTEXT_BYTES = 64 * 1024


class DataKeyProvider(Protocol):
    name: str

    def generate_data_key(
        self, key_id: str, encryption_context: dict[str, str]
    ) -> tuple[bytearray, bytes, str]: ...

    def decrypt_data_key(
        self,
        encrypted_data_key: bytes,
        key_id: str,
        encryption_context: dict[str, str],
    ) -> bytearray: ...


class AwsKmsProvider:
    """AWS KMS data-key provider with imports deferred to runtime."""

    name = "aws-kms"

    def __init__(self, region: str):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "AWS KMS support requires: pip install '.[kms-aws]'"
            ) from exc
        self.region = region
        self.client = boto3.client("kms", region_name=region)

    def generate_data_key(
        self, key_id: str, encryption_context: dict[str, str]
    ) -> tuple[bytearray, bytes, str]:
        response = self.client.generate_data_key(
            KeyId=key_id,
            KeySpec="AES_256",
            EncryptionContext=encryption_context,
        )
        return (
            bytearray(response["Plaintext"]),
            bytes(response["CiphertextBlob"]),
            str(response["KeyId"]),
        )

    def decrypt_data_key(
        self,
        encrypted_data_key: bytes,
        key_id: str,
        encryption_context: dict[str, str],
    ) -> bytearray:
        response = self.client.decrypt(
            KeyId=key_id,
            CiphertextBlob=encrypted_data_key,
            EncryptionContext=encryption_context,
        )
        return bytearray(response["Plaintext"])


def encryption_context(asset_type: str) -> dict[str, str]:
    allowed = {"heldout-catalog", "heldout-seed", "heldout-phrase-bank"}
    if asset_type not in allowed:
        raise ValueError(f"asset_type must be one of {sorted(allowed)}")
    return {
        "Application": "AccessBench",
        "AssetType": asset_type,
        "ScenarioVersion": "environment-lab-scenarios-v5",
    }


def _crypto() -> tuple[Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError(
            "sealed asset support requires: pip install '.[kms-aws]'"
        ) from exc
    return Cipher, algorithms, modes


def _canonical_header(header: dict[str, Any]) -> bytes:
    return json.dumps(
        header, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _zeroize(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def seal_file(
    source: str | Path,
    destination: str | Path,
    *,
    provider: DataKeyProvider,
    key_id: str,
    asset_type: str,
    region: str,
) -> dict[str, Any]:
    """Seal one file without ever writing its data key to disk."""
    source_path = Path(source)
    destination_path = Path(destination)
    if destination_path.exists():
        raise FileExistsError(
            f"refusing to overwrite sealed asset: {destination_path}"
        )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    context = encryption_context(asset_type)
    data_key, encrypted_data_key, resolved_key_id = provider.generate_data_key(
        key_id, context
    )
    nonce = os.urandom(12)
    header = {
        "schema_version": SCHEMA_VERSION,
        "provider": provider.name,
        "algorithm": "AES-256-GCM",
        "key_id": resolved_key_id,
        "region": region,
        "encryption_context": context,
        "encrypted_data_key": base64.b64encode(encrypted_data_key).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "plaintext_bytes": source_path.stat().st_size,
    }
    header_bytes = _canonical_header(header)
    if len(header_bytes) > MAX_HEADER_BYTES:
        _zeroize(data_key)
        raise ValueError("sealed asset header is too large")

    Cipher, algorithms, modes = _crypto()
    temporary_name: str | None = None
    try:
        encryptor = Cipher(
            algorithms.AES(bytes(data_key)), modes.GCM(nonce)
        ).encryptor()
        encryptor.authenticate_additional_data(header_bytes)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination_path.parent, delete=False
        ) as output:
            temporary_name = output.name
            os.chmod(temporary_name, 0o600)
            output.write(MAGIC)
            output.write(struct.pack(">I", len(header_bytes)))
            output.write(header_bytes)
            with source_path.open("rb") as input_file:
                for chunk in iter(lambda: input_file.read(CHUNK_BYTES), b""):
                    output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination_path)
        temporary_name = None
    finally:
        _zeroize(data_key)
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)

    return inspect_sealed(destination_path)


def _read_header(handle: Any, sealed_size: int) -> tuple[dict[str, Any], bytes, int]:
    if handle.read(len(MAGIC)) != MAGIC:
        raise ValueError("not an AccessBench sealed asset")
    raw_length = handle.read(4)
    if len(raw_length) != 4:
        raise ValueError("sealed asset header length is truncated")
    header_length = struct.unpack(">I", raw_length)[0]
    if not 0 < header_length <= MAX_HEADER_BYTES:
        raise ValueError("sealed asset header length is invalid")
    header_bytes = handle.read(header_length)
    if len(header_bytes) != header_length:
        raise ValueError("sealed asset header is truncated")
    header = json.loads(header_bytes)
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported sealed asset schema")
    if header.get("algorithm") != "AES-256-GCM":
        raise ValueError("unsupported sealed asset algorithm")
    ciphertext_offset = len(MAGIC) + 4 + header_length
    if sealed_size < ciphertext_offset + TAG_BYTES:
        raise ValueError("sealed asset ciphertext is truncated")
    return header, header_bytes, ciphertext_offset


def inspect_sealed(path: str | Path) -> dict[str, Any]:
    """Return non-secret routing metadata without exposing the wrapped key."""
    sealed_path = Path(path)
    sealed_size = sealed_path.stat().st_size
    with sealed_path.open("rb") as handle:
        prefix = handle.read(max(len(MAGIC), len(CATALOG_MAGIC)))
        handle.seek(0)
        if prefix.startswith(CATALOG_MAGIC):
            header, _, _ = _read_catalog_header(handle, sealed_size)
        else:
            header, _, _ = _read_header(handle, sealed_size)
    report = {
        "schema_version": header["schema_version"],
        "provider": header["provider"],
        "algorithm": header["algorithm"],
        "key_id": header["key_id"],
        "region": header["region"],
        "encryption_context": header["encryption_context"],
        "plaintext_bytes": header["plaintext_bytes"],
        "sealed_bytes": sealed_size,
    }
    if "content_layout" in header:
        report["content_layout"] = header["content_layout"]
        report["record_n"] = header["record_n"]
        report["record_plaintext_bytes"] = header["record_plaintext_bytes"]
        report["panel_id"] = header.get("panel_id")
        report["panel_status"] = header.get("panel_status")
        report["index_sha256"] = header["index_sha256"]
        report["scenario_version"] = header.get("scenario_version")
        report["oracle_version"] = header.get("oracle_version")
        report["split"] = header.get("split")
    return report


def unseal_bytes(
    path: str | Path,
    *,
    provider: DataKeyProvider,
) -> bytes:
    """Authenticate and decrypt an asset into controller memory."""
    sealed_path = Path(path)
    sealed_size = sealed_path.stat().st_size
    Cipher, algorithms, modes = _crypto()
    with sealed_path.open("rb") as handle:
        header, header_bytes, ciphertext_offset = _read_header(handle, sealed_size)
        context = header["encryption_context"]
        encrypted_data_key = base64.b64decode(
            header["encrypted_data_key"], validate=True
        )
        nonce = base64.b64decode(header["nonce"], validate=True)
        handle.seek(-TAG_BYTES, os.SEEK_END)
        tag = handle.read(TAG_BYTES)
        ciphertext_bytes = sealed_size - ciphertext_offset - TAG_BYTES
        handle.seek(ciphertext_offset)

        data_key = provider.decrypt_data_key(
            encrypted_data_key, header["key_id"], context
        )
        try:
            decryptor = Cipher(
                algorithms.AES(bytes(data_key)), modes.GCM(nonce, tag)
            ).decryptor()
            decryptor.authenticate_additional_data(header_bytes)
            remaining = ciphertext_bytes
            plaintext = bytearray()
            while remaining:
                chunk = handle.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise ValueError("sealed asset ciphertext is truncated")
                remaining -= len(chunk)
                plaintext.extend(decryptor.update(chunk))
            plaintext.extend(decryptor.finalize())
        finally:
            _zeroize(data_key)

    if len(plaintext) != int(header["plaintext_bytes"]):
        _zeroize(plaintext)
        raise ValueError("sealed asset plaintext length does not match its header")
    result = bytes(plaintext)
    _zeroize(plaintext)
    return result


def read_sealed_jsonl(
    path: str | Path,
    *,
    provider: DataKeyProvider,
) -> list[dict[str, Any]]:
    metadata = inspect_sealed(path)
    if metadata.get("content_layout") == "record-aead-jsonl":
        with SealedCatalogReader(path, provider=provider) as reader:
            return [reader.read_entry(entry) for entry in reader.entries]
    raw = unseal_bytes(path, provider=provider)
    try:
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    finally:
        temporary = bytearray(raw)
        _zeroize(temporary)


CATALOG_PUBLIC_INDEX_FIELDS = frozenset((
    "record_id",
    "offset",
    "length",
    "nonce",
))


def _validate_catalog_entries(entries: Any, record_n: int) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or len(entries) != record_n:
        raise ValueError("sealed catalog record count does not match its index")
    record_ids: set[str] = set()
    expected_offset = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != CATALOG_PUBLIC_INDEX_FIELDS:
            raise ValueError("sealed catalog index contains non-routing fields")
        record_id = entry["record_id"]
        if not isinstance(record_id, str) or len(record_id) != 32:
            raise ValueError("sealed catalog record ID is invalid")
        if record_id in record_ids:
            raise ValueError("sealed catalog record IDs are not unique")
        record_ids.add(record_id)
        if int(entry["offset"]) != expected_offset:
            raise ValueError("sealed catalog offsets are not contiguous")
        length = int(entry["length"])
        if length != CATALOG_RECORD_PLAINTEXT_BYTES + TAG_BYTES:
            raise ValueError("sealed catalog record length is not uniform")
        expected_offset += length
        nonce = base64.b64decode(entry["nonce"], validate=True)
        if len(nonce) != 12:
            raise ValueError("sealed catalog nonce is invalid")
    return entries


def _read_catalog_header(
    handle: Any, sealed_size: int
) -> tuple[dict[str, Any], bytes, int]:
    if handle.read(len(CATALOG_MAGIC)) != CATALOG_MAGIC:
        raise ValueError("not an AccessBench record-sealed catalog")
    raw_length = handle.read(4)
    if len(raw_length) != 4:
        raise ValueError("sealed catalog header length is truncated")
    header_length = struct.unpack(">I", raw_length)[0]
    if not 0 < header_length <= MAX_HEADER_BYTES:
        raise ValueError("sealed catalog header length is invalid")
    header_bytes = handle.read(header_length)
    if len(header_bytes) != header_length:
        raise ValueError("sealed catalog header is truncated")
    header = json.loads(header_bytes)
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported sealed catalog schema")
    if header.get("content_layout") != "record-aead-jsonl":
        raise ValueError("unsupported sealed catalog layout")
    index_bytes = int(header.get("index_bytes", 0))
    if not 0 < index_bytes <= MAX_INDEX_BYTES:
        raise ValueError("sealed catalog index length is invalid")
    index_offset = len(CATALOG_MAGIC) + 4 + header_length
    if sealed_size < index_offset + index_bytes:
        raise ValueError("sealed catalog index is truncated")
    record_n = int(header.get("record_n", 0))
    if record_n <= 0:
        raise ValueError("sealed catalog record count is invalid")
    if int(header.get("record_plaintext_bytes", 0)) != CATALOG_RECORD_PLAINTEXT_BYTES:
        raise ValueError("sealed catalog record size is unsupported")
    expected_size = (
        index_offset
        + index_bytes
        + record_n * (CATALOG_RECORD_PLAINTEXT_BYTES + TAG_BYTES)
    )
    if sealed_size != expected_size:
        raise ValueError("sealed catalog byte length does not match its header")
    return header, header_bytes, index_offset


def seal_jsonl_catalog(
    source: str | Path,
    destination: str | Path,
    *,
    provider: DataKeyProvider,
    key_id: str,
    region: str,
    select_core_panel: bool = True,
) -> dict[str, Any]:
    """Seal an opaque, fixed-size, independently authenticated trial pack.

    Production sealing selects the exact core panel before encryption. The
    plaintext index contains only random record handles and byte routing. It
    contains no trial IDs, policy cells, mechanisms, profiles, labels, prompt
    lengths, or other assignment clues.
    """
    source_path = Path(source)
    destination_path = Path(destination)
    if destination_path.exists():
        raise FileExistsError(
            f"refusing to overwrite sealed asset: {destination_path}"
        )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with source_path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if select_core_panel:
        from .validate import validate_catalog
        from .panel import (
            SEALED_PANEL_CANDIDATE_STATUS,
            SEALED_PANEL_ID,
            build_core_panel,
        )

        source_validation = validate_catalog(rows)
        if not source_validation["ok"]:
            raise ValueError(
                "sealed source construction matrix failed validation: "
                + "; ".join(source_validation["failures"][:3])
            )
        rows = build_core_panel(rows)
        panel_id = SEALED_PANEL_ID
        panel_status = SEALED_PANEL_CANDIDATE_STATUS
    else:
        panel_id = None
        panel_status = "test-pack"
    if not rows:
        raise ValueError("catalog has no records")
    scenario_versions = {row.get("scenario_version") for row in rows}
    oracle_versions = {row.get("oracle_version") for row in rows}
    splits = {row.get("split") for row in rows}
    if len(scenario_versions) != 1 or None in scenario_versions:
        raise ValueError("sealed panel must use one scenario version")
    if len(oracle_versions) != 1 or None in oracle_versions:
        raise ValueError("sealed panel must use one oracle version")
    if len(splits) != 1 or None in splits:
        raise ValueError("sealed panel must use one catalog split")
    if select_core_panel and splits != {"heldout"}:
        raise ValueError("production sealed panel must come from the heldout split")
    secrets.SystemRandom().shuffle(rows)
    encoded_rows = [
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
        for row in rows
    ]
    oversized = [len(row) for row in encoded_rows if len(row) > CATALOG_RECORD_PLAINTEXT_BYTES]
    if oversized:
        raise ValueError(
            "catalog row exceeds fixed sealed record size: "
            f"{max(oversized)} > {CATALOG_RECORD_PLAINTEXT_BYTES}"
        )

    entries: list[dict[str, Any]] = []
    ciphertext_length = CATALOG_RECORD_PLAINTEXT_BYTES + TAG_BYTES
    for index in range(len(encoded_rows)):
        entries.append({
            "record_id": secrets.token_hex(16),
            "offset": index * ciphertext_length,
            "length": ciphertext_length,
            "nonce": base64.b64encode(os.urandom(12)).decode("ascii"),
        })
    index_bytes = json.dumps(
        entries, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(index_bytes) > MAX_INDEX_BYTES:
        raise ValueError("sealed catalog index is too large")

    context = encryption_context("heldout-catalog")
    data_key, encrypted_data_key, resolved_key_id = provider.generate_data_key(
        key_id, context
    )
    header = {
        "schema_version": SCHEMA_VERSION,
        "provider": provider.name,
        "algorithm": "AES-256-GCM",
        "content_layout": "record-aead-jsonl",
        "key_id": resolved_key_id,
        "region": region,
        "encryption_context": context,
        "encrypted_data_key": base64.b64encode(encrypted_data_key).decode("ascii"),
        "plaintext_bytes": len(entries) * CATALOG_RECORD_PLAINTEXT_BYTES,
        "record_n": len(entries),
        "record_plaintext_bytes": CATALOG_RECORD_PLAINTEXT_BYTES,
        "panel_id": panel_id,
        "panel_status": panel_status,
        "scenario_version": next(iter(scenario_versions)),
        "oracle_version": next(iter(oracle_versions)),
        "split": next(iter(splits)),
        "index_bytes": len(index_bytes),
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
    }
    header_bytes = _canonical_header(header)
    if len(header_bytes) > MAX_HEADER_BYTES:
        _zeroize(data_key)
        raise ValueError("sealed catalog header is too large")

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        _zeroize(data_key)
        raise RuntimeError(
            "sealed asset support requires: pip install '.[kms-aws]'"
        ) from exc

    temporary_name: str | None = None
    try:
        cipher = AESGCM(bytes(data_key))
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination_path.parent, delete=False
        ) as output:
            temporary_name = output.name
            os.chmod(temporary_name, 0o600)
            output.write(CATALOG_MAGIC)
            output.write(struct.pack(">I", len(header_bytes)))
            output.write(header_bytes)
            output.write(index_bytes)
            for entry, raw_row in zip(entries, encoded_rows, strict=True):
                nonce = base64.b64decode(entry["nonce"], validate=True)
                aad = header_bytes + b"\n" + _canonical_header(entry)
                padded = raw_row.ljust(CATALOG_RECORD_PLAINTEXT_BYTES, b" ")
                output.write(cipher.encrypt(nonce, padded, aad))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination_path)
        temporary_name = None
    finally:
        _zeroize(data_key)
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return inspect_sealed(destination_path)


def read_sealed_catalog_index(path: str | Path) -> list[dict[str, Any]]:
    """Read the opaque routing index without exposing case assignment."""
    sealed_path = Path(path)
    sealed_size = sealed_path.stat().st_size
    with sealed_path.open("rb") as handle:
        header, _, index_offset = _read_catalog_header(handle, sealed_size)
        handle.seek(index_offset)
        index_bytes = handle.read(header["index_bytes"])
    if hashlib.sha256(index_bytes).hexdigest() != header["index_sha256"]:
        raise ValueError("sealed catalog index digest does not match")
    entries = json.loads(index_bytes)
    return _validate_catalog_entries(entries, int(header["record_n"]))


class SealedCatalogReader:
    """Decrypt selected trial records while leaving the remaining bank sealed."""

    def __init__(self, path: str | Path, *, provider: DataKeyProvider):
        self.path = Path(path)
        sealed_size = self.path.stat().st_size
        with self.path.open("rb") as handle:
            self.header, self.header_bytes, index_offset = _read_catalog_header(
                handle, sealed_size
            )
            handle.seek(index_offset)
            index_bytes = handle.read(self.header["index_bytes"])
        if hashlib.sha256(index_bytes).hexdigest() != self.header["index_sha256"]:
            raise ValueError("sealed catalog index digest does not match")
        self.entries = _validate_catalog_entries(
            json.loads(index_bytes), int(self.header["record_n"])
        )
        self.data_offset = index_offset + self.header["index_bytes"]
        encrypted_key = base64.b64decode(
            self.header["encrypted_data_key"], validate=True
        )
        self.data_key = provider.decrypt_data_key(
            encrypted_key,
            self.header["key_id"],
            self.header["encryption_context"],
        )
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            _zeroize(self.data_key)
            raise RuntimeError(
                "sealed asset support requires: pip install '.[kms-aws]'"
            ) from exc
        self.cipher = AESGCM(bytes(self.data_key))
        self.closed = False

    def read_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        if self.closed:
            raise RuntimeError("sealed catalog reader is closed")
        offset = int(entry["offset"])
        length = int(entry["length"])
        with self.path.open("rb") as handle:
            handle.seek(self.data_offset + offset)
            ciphertext = handle.read(length)
        if len(ciphertext) != length:
            raise ValueError("sealed catalog record is truncated")
        nonce = base64.b64decode(entry["nonce"], validate=True)
        aad = self.header_bytes + b"\n" + _canonical_header(entry)
        plaintext = self.cipher.decrypt(nonce, ciphertext, aad)
        if len(plaintext) != CATALOG_RECORD_PLAINTEXT_BYTES:
            raise ValueError("sealed catalog record has an invalid plaintext size")
        row = json.loads(plaintext)
        if not isinstance(row, dict):
            raise ValueError("sealed catalog record must contain a JSON object")
        return row

    def close(self) -> None:
        if not self.closed:
            _zeroize(self.data_key)
            self.cipher = None
            self.closed = True

    def __enter__(self) -> "SealedCatalogReader":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
