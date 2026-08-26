# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Record independent human signoff on the 600-prompt bank, one prompt at a time.

The ledger has always carried a `human_signoff` field set to `pending` for all
600 prompts. This is the tool that changes it, and the only thing that may:
a named person reading a prompt and pressing a key. It never auto-approves, it
never uses a model, and it writes the reviewer name and an ISO timestamp beside
each decision so the claim is auditable.

    python scripts/human_signoff.py --reviewer "PJ Mullin"
    python scripts/human_signoff.py --reviewer "PJ Mullin" --sample 60
    python scripts/human_signoff.py --status

Keys: y accept, n reject, s skip, q save and quit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "verification" / "prompt_bank_human_review_v1.jsonl"


def load() -> list[dict]:
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(rows: list[dict]) -> None:
    tmp = LEDGER.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8",
    )
    tmp.replace(LEDGER)


def status(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[str(r.get("human_signoff", "pending"))] = counts.get(
            str(r.get("human_signoff", "pending")), 0
        ) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reviewer", help="name recorded beside every decision")
    ap.add_argument("--sample", type=int, help="review a stratified sample of this size")
    ap.add_argument("--seed", type=int, default=7, help="sample seed (default 7)")
    ap.add_argument("--status", action="store_true", help="print counts and exit")
    args = ap.parse_args()

    rows = load()
    if args.status:
        counts = status(rows)
        total = len(rows)
        print(f"{total} prompts in the ledger")
        for state, n in sorted(counts.items()):
            print(f"  {state:10} {n:4}  {100*n/total:5.1f}%")
        return 0

    if not args.reviewer:
        print("--reviewer is required: signoff is attributed to a person")
        return 2

    queue = [r for r in rows if str(r.get("human_signoff", "pending")) == "pending"]
    if args.sample:
        # stratified by leak type so a sample covers the whole bank
        by_type: dict[str, list[dict]] = {}
        for r in queue:
            by_type.setdefault(str(r.get("mechanism") or r.get("leak_type") or "unknown"), []).append(r)
        rng = random.Random(args.seed)
        per = max(1, args.sample // max(1, len(by_type)))
        picked: list[dict] = []
        for _, group in sorted(by_type.items()):
            rng.shuffle(group)
            picked.extend(group[:per])
        queue = picked[: args.sample]

    if not queue:
        print("nothing pending")
        return 0

    print(f"{len(queue)} prompt(s) to review as {args.reviewer}. y accept, n reject, s skip, q quit.\n")
    reviewed = 0
    for i, row in enumerate(queue, 1):
        print("=" * 72)
        print(f"[{i}/{len(queue)}] leak type: {row.get('mechanism') or row.get('leak_type')}"
              f"   workflow: {row.get('blueprint_id')}   surface: {row.get('surface')}")
        print("-" * 72)
        print((row.get("prompt") or "").strip())
        print("-" * 72)
        while True:
            try:
                key = input("y/n/s/q > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                key = "q"
            if key in {"y", "n", "s", "q"}:
                break
        if key == "q":
            break
        if key == "s":
            continue
        row["human_signoff"] = "pass" if key == "y" else "reject"
        row["human_reviewer"] = args.reviewer
        row["human_signoff_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        reviewed += 1

    save(rows)
    counts = status(rows)
    print(f"\nrecorded {reviewed} decision(s) as {args.reviewer}")
    for state, n in sorted(counts.items()):
        print(f"  {state:10} {n:4}")
    print("\nThe ledger is the only place a signoff claim may come from. Anything "
          "still pending must be reported as pending, never rounded up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
