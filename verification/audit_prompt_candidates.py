#!/usr/bin/env python3
# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Combine and audit the 600 newly authored public prompt candidates."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "environment_lab"
sys.path.insert(0, str(LAB))

from accessbench_env.blueprints import BLUEPRINT_BY_ID
from author_prompt_bank import APP_NAMES, DISALLOWED_TERMS, workflow_batches


SURFACE_IDS = (0, 1, 2, 4)
SURFACE_NAMES = (
    "direct_assignment",
    "work_item_handoff",
    "business_review_preparation",
    "conversational_team_request",
)


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def load_candidates(directory: Path) -> list[dict]:
    expected = workflow_batches()
    rows = []
    for leak_type, workflows in expected.items():
        path = directory / f"{leak_type}.json"
        if not path.is_file():
            raise ValueError(f"missing candidate batch: {leak_type}")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("status") != "candidate":
            raise ValueError(f"candidate batch is not accepted: {leak_type}")
        by_id = {
            row["blueprint_id"]: row["prompts"]
            for row in artifact["workflows"]
        }
        for metadata in workflows:
            blueprint_id = metadata["blueprint_id"]
            prompts = by_id.get(blueprint_id, [])
            if len(prompts) != 4:
                raise ValueError(f"{blueprint_id}: candidate prompt count is not four")
            for position, prompt in enumerate(prompts):
                rows.append({
                    "prompt_id": f"{blueprint_id}:surface-{SURFACE_IDS[position]}",
                    "blueprint_id": blueprint_id,
                    "leak_type": leak_type,
                    "surface": SURFACE_IDS[position],
                    "surface_name": SURFACE_NAMES[position],
                    "prompt": prompt,
                    "authoring_batch": path.name,
                })
    return rows


def audit(rows: list[dict]) -> tuple[list[dict], dict]:
    by_blueprint = defaultdict(list)
    by_type = defaultdict(list)
    normalized_prompts = [normalize(row["prompt"]) for row in rows]
    for index, row in enumerate(rows):
        by_blueprint[row["blueprint_id"]].append(index)
        by_type[row["leak_type"]].append(index)

    pair_scores = {}
    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            pair_scores[(left, right)] = SequenceMatcher(
                None, normalized_prompts[left], normalized_prompts[right]
            ).ratio()

    def score(left: int, right: int) -> float:
        if left == right:
            return 1.0
        return pair_scores[
            (left, right) if left < right else (right, left)
        ]

    opening_counts = Counter(
        tuple(normalize(row["prompt"]).split()[:3]) for row in rows
    )
    audited = []
    for row_index, row in enumerate(rows):
        prompt = row["prompt"]
        normalized = normalized_prompts[row_index]
        blueprint = BLUEPRINT_BY_ID[row["blueprint_id"]]
        within = [
            candidate_index
            for candidate_index in by_blueprint[row["blueprint_id"]]
            if candidate_index != row_index
        ]
        same_type = [
            candidate_index
            for candidate_index in by_type[row["leak_type"]]
            if rows[candidate_index]["blueprint_id"] != row["blueprint_id"]
        ]
        global_candidates = [
            candidate_index
            for candidate_index, candidate in enumerate(rows)
            if candidate["blueprint_id"] != row["blueprint_id"]
        ]
        nearest_within_index = max(
            within, key=lambda candidate_index: score(row_index, candidate_index)
        )
        nearest_type_index = max(
            same_type,
            key=lambda candidate_index: score(row_index, candidate_index),
        )
        nearest_global_index = max(
            global_candidates,
            key=lambda candidate_index: score(row_index, candidate_index),
        )
        nearest_within = rows[nearest_within_index]
        nearest_type = rows[nearest_type_index]
        nearest_global = rows[nearest_global_index]
        within_score = score(row_index, nearest_within_index)
        type_score = score(row_index, nearest_type_index)
        global_score = score(row_index, nearest_global_index)
        tokens = normalized.split()
        reasons = []
        if not 14 <= len(prompt.split()) <= 36:
            reasons.append("length_outside_14_to_36")
        if any(term in normalized for term in DISALLOWED_TERMS):
            reasons.append("disallowed_or_benchmark_cue_term")
        if any(left == right for left, right in zip(tokens, tokens[1:])):
            reasons.append("repeated_adjacent_word")
        if APP_NAMES[blueprint.source_app].lower() not in normalized:
            reasons.append("source_app_absent")
        if APP_NAMES[blueprint.sink_app].lower() not in normalized:
            reasons.append("destination_app_absent")
        if within_score >= 0.88:
            reasons.append("within_workflow_near_duplicate")
        if type_score >= 0.90:
            reasons.append("same_type_cross_workflow_near_duplicate")
        if global_score >= 0.93:
            reasons.append("global_cross_workflow_near_duplicate")
        opening = tuple(tokens[:3])
        if opening_counts[opening] > 12:
            reasons.append("bank_wide_repeated_opening")
        audited.append({
            **row,
            "word_count": len(prompt.split()),
            "opening": " ".join(opening),
            "opening_frequency": opening_counts[opening],
            "nearest_within_prompt_id": nearest_within["prompt_id"],
            "nearest_within_similarity": round(within_score, 4),
            "nearest_same_type_prompt_id": nearest_type["prompt_id"],
            "nearest_same_type_similarity": round(type_score, 4),
            "nearest_global_prompt_id": nearest_global["prompt_id"],
            "nearest_global_similarity": round(global_score, 4),
            "decision": "rewrite_required" if reasons else "candidate_for_human_review",
            "reasons": sorted(set(reasons)),
        })

    five_grams = defaultdict(set)
    for row in rows:
        tokens = normalize(row["prompt"]).split()
        for index in range(max(0, len(tokens) - 4)):
            five_grams[tuple(tokens[index:index + 5])].add(row["blueprint_id"])
    repeated_five_grams = sorted(
        (
            len(blueprints),
            " ".join(gram),
        )
        for gram, blueprints in five_grams.items()
        if len(blueprints) >= 4
    )
    summary = {
        "prompt_n": len(rows),
        "workflow_n": len(by_blueprint),
        "leak_type_n": len(by_type),
        "surface_counts": dict(sorted(Counter(
            row["surface_name"] for row in rows
        ).items())),
        "decision_counts": dict(sorted(Counter(
            row["decision"] for row in audited
        ).items())),
        "reason_counts": dict(sorted(Counter(
            reason for row in audited for reason in row["reasons"]
        ).items())),
        "highest_openings": [
            {"opening": " ".join(opening), "n": count}
            for opening, count in opening_counts.most_common(20)
        ],
        "repeated_five_grams": [
            {"workflow_n": count, "phrase": phrase}
            for count, phrase in repeated_five_grams[-30:][::-1]
        ],
    }
    return audited, summary


def main() -> None:
    directory = ROOT / "verification" / "prompt_candidates_v1"
    rows = load_candidates(directory)
    if len(rows) != 600:
        raise SystemExit(f"expected 600 candidates, found {len(rows)}")
    audited, summary = audit(rows)
    jsonl = ROOT / "verification" / "prompt_bank_v1_candidates.jsonl"
    jsonl.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in audited),
        encoding="utf-8",
    )
    report = ROOT / "verification" / "PROMPT_BANK_V1_CANDIDATE_AUDIT.md"
    lines = [
        "# AccessBench v1 candidate prompt audit",
        "",
        "This report audits the newly authored 600-prompt candidate bank after",
        "all 25 leak-type batches passed their local gates. No prompt is admitted",
        "without a final human decision.",
        "",
        "## Summary",
        "",
        f"- Prompts: {summary['prompt_n']}",
        f"- Workflows: {summary['workflow_n']}",
        f"- Executable leak types: {summary['leak_type_n']}",
        f"- Candidate for human review: {summary['decision_counts'].get('candidate_for_human_review', 0)}",
        f"- Rewrite required: {summary['decision_counts'].get('rewrite_required', 0)}",
        "",
        "Automated rewrite reasons:",
        "",
    ]
    for reason, count in summary["reason_counts"].items():
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "Most common three-word openings:", ""])
    for item in summary["highest_openings"]:
        lines.append(f"- {item['n']}: `{item['opening']}`")
    lines.extend(["", "Five-word phrases spanning at least four workflows:", ""])
    for item in summary["repeated_five_grams"]:
        lines.append(f"- {item['workflow_n']}: `{item['phrase']}`")
    lines.extend([
        "",
        "## Per-prompt evidence",
        "",
        "The complete prompt text, nearest-neighbor evidence, decision, and reasons",
        "for all 600 prompts are in `prompt_bank_v1_candidates.jsonl`.",
    ])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
