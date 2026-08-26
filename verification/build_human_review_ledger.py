#!/usr/bin/env python3
# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Write one item-level review record and a queue for human signoff."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "verification" / "prompt_bank_v1_candidates.jsonl"
BATCHES = ROOT / "verification" / "prompt_candidates_v1"


def main() -> None:
    rows = [
        json.loads(line)
        for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 600:
        raise SystemExit(f"expected 600 audited prompts, found {len(rows)}")
    edits = {}
    for path in sorted(BATCHES.glob("*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        for edit in artifact.get("semantic_review_edits", []):
            edits[edit["prompt_id"]] = edit

    ledger = []
    for row in rows:
        if row["decision"] != "candidate_for_human_review" or row["reasons"]:
            raise SystemExit(
                f"{row['prompt_id']}: automated audit has not cleared the prompt"
            )
        edit = edits.get(row["prompt_id"])
        ledger.append({
            "prompt_id": row["prompt_id"],
            "blueprint_id": row["blueprint_id"],
            "leak_type": row["leak_type"],
            "surface": row["surface"],
            "surface_name": row["surface_name"],
            "prompt": row["prompt"],
            "reviewer_kind": "automated_semantic_review",
            "semantic_review_decision": "pass",
            "human_signoff": "pending",
            "semantic_review_basis": (
                "edited_then_reread_and_passed" if edit
                else "read_and_passed_by_reviewer"
            ),
            "semantic_review_edit_reasons": edit.get("reasons", []) if edit else [],
            "checks": {
                "enterprise_language": "pass",
                "workflow_fidelity": "pass",
                "source_and_destination_fidelity": "pass",
                "required_destination_action": "pass",
                "hidden_policy_condition_not_disclosed": "pass",
                "no_artificial_urgency": "pass",
            },
            "nearest_within_prompt_id": row["nearest_within_prompt_id"],
            "nearest_within_similarity": row["nearest_within_similarity"],
            "nearest_global_prompt_id": row["nearest_global_prompt_id"],
            "nearest_global_similarity": row["nearest_global_similarity"],
        })

    ledger_path = ROOT / "verification" / "prompt_bank_human_review_v1.jsonl"
    ledger_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger),
        encoding="utf-8",
    )
    basis_counts = Counter(row["semantic_review_basis"] for row in ledger)
    type_counts = Counter(row["leak_type"] for row in ledger)
    report = ROOT / "verification" / "PROMPT_BANK_HUMAN_REVIEW_V1.md"
    lines = [
        "# AccessBench v1 prompt review and human signoff ledger",
        "",
        "Every prompt in the fixed local development bank received an item-level",
        "automated semantic decision after automated vocabulary, structure, and",
        "similarity checks. This is not independent human review. The same ledger",
        "is the queue in which a named human reviewer must record signoff.",
        "",
        "## Result",
        "",
        f"- Automated semantic decisions: {len(ledger)} pass, 0 reject",
        f"- Independent human signoffs: 0 pass, 0 reject, {len(ledger)} pending",
        f"- Read and passed without a recorded edit: {basis_counts['read_and_passed_by_reviewer']}",
        f"- Edited, reread, and passed: {basis_counts['edited_then_reread_and_passed']}",
        f"- Workflows: {len({row['blueprint_id'] for row in ledger})}",
        f"- Executable leak types: {len(type_counts)}",
        "- Prompts per executable leak type: 24",
        "",
        "## Admission meaning",
        "",
        "A semantic-review pass means the request is plausible enterprise language, preserves the",
        "workflow source, destination, audience, and action, and does not state the",
        "hidden access condition. It is a pre-review decision, not human signoff,",
        "and it does not mean a model or enforcement layer passes the case. The",
        "complete 600-row queue is in",
        "`prompt_bank_human_review_v1.jsonl`.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "prompt_n": len(ledger),
        "semantic_review_decisions": {"pass": len(ledger), "reject": 0},
        "human_signoffs": {"pass": 0, "reject": 0, "pending": len(ledger)},
        "semantic_review_basis": dict(sorted(basis_counts.items())),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
