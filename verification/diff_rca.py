# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Differential root cause: episodes the control passed and enforcement lost.

Diagnostic only. Reads retained raw episodes, never changes a score. Run it
after aggregation to understand where an enforcement layer costs task success.
"""
import json, sys, collections, glob, os, re

def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]

def classify(r):
    """Bucket one failed governed episode."""
    err = (r.get("agent_error") or "") + " " + (r.get("error") or "")
    status = r.get("final_status")
    blocked = int(r.get("blocked_calls") or 0)
    if re.search(r"JSONDecode|Expecting value|json\.decoder|schema|ValidationError", err, re.I):
        return "schema_format"
    if status == "capability_failure":
        return "runtime_exception"
    if status == "refused":
        return "refusal"
    if status == "abandoned" and blocked > 0:
        return "blocked_loop"
    if status == "abandoned":
        return "abandoned_no_block"
    if r.get("blocked_delivery"):
        return "blocked_delivery"
    if status == "completed" and not r.get("task_success"):
        return "completed_but_task_incomplete"
    return "other:" + str(status)

def analyse(path, label):
    recs = load(path)
    by = {}
    for r in recs:
        by[(r["enforcer"], r["trial_id"], r["repeat"])] = r
    trials = sorted({r["trial_id"] for r in recs})
    repeats = sorted({r["repeat"] for r in recs})
    diffs = []
    for t in trials:
        for k in repeats:
            c = by.get(("none", t, k)); g = by.get(("label_governance", t, k))
            if not c or not g: continue
            if c.get("governed_task_pass") and not g.get("governed_task_pass"):
                diffs.append((t, k, c, g))
    buckets = collections.Counter(classify(g) for _, _, _, g in diffs)
    return label, len(recs), diffs, buckets

def snippet(g, n=3):
    tr = g.get("subject_trace") or []
    out = []
    for e in tr[-n:]:
        kind = e.get("kind")
        if kind == "tool_call":
            out.append(f'tool_call {e.get("tool_name")} args={json.dumps(e.get("arguments"))[:180]}')
        elif kind == "tool_result":
            out.append(f'tool_result {e.get("tool_name")} -> {str(e.get("result"))[:180]}')
        else:
            out.append(f'{kind}: {json.dumps(e)[:180]}')
    return out

files = [
    ("environment_lab/results_raw/20260819T075637903855Z-gpt-4o.jsonl", "gpt-4o"),
    ("environment_lab/results_raw/20260819T080943026636Z-gpt-5-4.jsonl", "gpt-5.4"),
    ("environment_lab/results_raw/20260819T094424665844Z-gpt-5-6-sol.jsonl", "gpt-5.6-sol"),
]
allb = collections.Counter(); total = 0; samples = {}
per_model = []
for path, label in files:
    label, n, diffs, buckets = analyse(path, label)
    per_model.append((label, len(diffs), buckets))
    allb.update(buckets); total += len(diffs)
    for t, k, c, g in diffs:
        b = classify(g)
        samples.setdefault(b, (label, t, k, c, g))

print("## Differential: control passed, governed failed\n")
print("| model | control-pass episodes lost under enforcement |")
print("|---|---|")
for label, n, _ in per_model:
    print(f"| {label} | {n} |")
print(f"| **all three** | **{total}** |\n")

names = {
    "schema_format": "Schema / formatting error (JSON decode, redaction injection)",
    "blocked_loop": "Unhandled 403 loop (retried blocked call to step limit)",
    "refusal": "Prompt-pollution refusal (safety refusal after governance markers)",
    "runtime_exception": "Unhandled runtime exception (agent crash)",
    "blocked_delivery": "Legitimate delivery blocked by the gate (no agent error)",
    "abandoned_no_block": "Abandoned with no block observed",
    "completed_but_task_incomplete": "Completed turn, task artifact incomplete",
}
print("| failure mode | episodes | share |")
print("|---|---|---|")
for b, c in allb.most_common():
    pretty = names.get(b, b)
    print(f"| {pretty} | {c} | {100*c/total:.1f}% |")
print()
print("### Per model\n")
print("| failure mode | " + " | ".join(l for l, _, _ in per_model) + " |")
print("|---|" + "---|"*len(per_model))
for b in [x for x, _ in allb.most_common()]:
    print(f"| {names.get(b,b)} | " + " | ".join(str(bk.get(b,0)) for _, _, bk in per_model) + " |")
print()
top = [b for b, _ in allb.most_common(2)]
for b in top:
    label, t, k, c, g = samples[b]
    print(f"\n### Snippet: {names.get(b,b)}  ({label}, trial {t}, repeat {k})\n")
    print(f"control final_status={c.get('final_status')} task_success={c.get('task_success')} blocked={c.get('blocked_calls')}")
    print(f"governed final_status={g.get('final_status')} task_success={g.get('task_success')} blocked={g.get('blocked_calls')} refusal={g.get('refusal')} agent_error={g.get('agent_error')}")
    print("last 3 subject-trace entries before the end:")
    for line in snippet(g):
        print("  " + line)
    fa = (g.get("final_answer") or "")[:300]
    if fa: print("final_answer: " + fa.replace("\n"," "))
