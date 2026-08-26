#!/usr/bin/env python3
# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Prove that every scored case has an oracle-constructible safe path.

This is a feasibility proof, not a benchmark defense. The selective reference
control is intentionally allowed to use oracle facts so it can answer one
question only: can the required benign task material reach the destination
while every policy-forbidden exact carrier stays out? No result produced by
this script is eligible for a leaderboard.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "environment_lab"
sys.path.insert(0, str(LAB))

from accessbench_env.models import Decision
from accessbench_env.oracle import evaluate
from accessbench_env.panel import build_core_panel
from accessbench_env.policy import decide_fact
from accessbench_env.sandbox import Sandbox


class OracleSelectiveReference:
    """Remove exactly the forbidden carriers at each governed boundary."""

    name = "oracle_selective_reference_not_a_benchmark_defense"

    def __init__(self, trial: dict[str, Any]) -> None:
        self.trial = trial
        self.facts = trial["facts"]

    def decide(self, event: dict[str, Any]) -> Decision:
        payload = event.get("payload", "")
        revised = payload
        removed = []
        for fact in self.facts:
            carrier = fact.get("carrier", "")
            if not carrier or carrier not in revised:
                continue
            allowed, reason = decide_fact(
                self.trial["enterprise_profile"],
                fact,
                event,
                self.trial,
            )
            if not allowed:
                revised = revised.replace(carrier, "[redacted]")
                removed.append(reason)
        if revised != payload:
            return Decision("rewrite", "; ".join(sorted(set(removed))), revised)
        return Decision("allow", "no forbidden exact carrier at this boundary")


def main() -> None:
    catalog = LAB / "catalog" / "public.jsonl"
    rows = [
        json.loads(line)
        for line in catalog.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    panel = build_core_panel(rows)
    failures = []
    counts = Counter()
    for trial in panel:
        run = Sandbox(
            trial,
            OracleSelectiveReference(trial),
        ).run_reference()
        result = evaluate(trial, run)
        counts["case_n"] += 1
        counts["task_success_n"] += int(result["task_success"])
        counts["no_verbatim_violation_n"] += int(
            not result["verbatim_violation"]
        )
        counts["governed_task_pass_n"] += int(
            result["governed_task_pass"]
        )
        if not result["governed_task_pass"]:
            failures.append({
                "trial_id": trial["trial_id"],
                "blueprint_id": trial["blueprint_id"],
                "mechanism": trial["mechanism"],
                "flow_variant": trial["flow_variant"],
                "enterprise_profile_id": trial["enterprise_profile_id"],
                "carrier_style": trial["carrier_style"],
                "label_regime": trial["label_regime"],
                "task_success": result["task_success"],
                "verbatim_violation": result["verbatim_violation"],
                "policy_reasons": result["policy_reasons"],
                "final_status": run["final_status"],
                "error": run["error"],
            })

    output = ROOT / "verification" / "core_solvability_v1.json"
    artifact = {
        "schema_version": "accessbench-core-solvability-v1",
        "status": "pass" if not failures else "fail",
        "scope": "oracle_constructibility_only_not_leaderboard_evidence",
        "counts": dict(sorted(counts.items())),
        "failures": failures,
    }
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(f"{len(failures)} core cases lack a constructed safe path")


if __name__ == "__main__":
    main()
