#!/usr/bin/env python3
# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Materialize the exact 600-case local development bank."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "environment_lab"
sys.path.insert(0, str(LAB))

from accessbench_env.panel import build_core_panel, challenge_band, core_panel_manifest


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = LAB / "catalog" / "public.jsonl"
    destination = LAB / "catalog" / "core_v2.jsonl"
    rows = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    panel = build_core_panel(rows)
    destination.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in panel
        ),
        encoding="utf-8",
    )
    manifest = core_panel_manifest(rows)
    manifest.update({
        "catalog_file": destination.name,
        "catalog_sha256": sha256(destination),
        "source_generation_matrix": source.name,
        "source_generation_matrix_sha256": sha256(source),
        "allowed_case_n": sum(
            challenge_band(row) in {"foundation_allow", "contextual_allow"}
            for row in panel
        ),
        "forbidden_case_n": sum(
            challenge_band(row) in {"direct_boundary", "contextual_deny"}
            for row in panel
        ),
        "carrier_style_counts": dict(sorted(Counter(
            row["carrier_style"] for row in panel
        ).items())),
        "label_regime_counts": dict(sorted(Counter(
            row["label_regime"] for row in panel
        ).items())),
    })
    manifest_path = LAB / "catalog" / "core_v2_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
