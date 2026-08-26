# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Cross-model AccessBench sweep with the refusal covariate.

Runs one agent across the full PDP ladder and reports, per policy:
  score        macro score over families (headline)
  acted_score  score over ONLY the tasks the model actually attempted
  refusal_rate fraction of deliverable tasks the model declined / no-oped

acted_score is the honest number: it isolates the enforcement stack from the
model's own reticence. That is the whole reason for local models.

    # offline sanity (no GPU):
    python -m docs.run_sweep

    # against a real vLLM server:
    python -m docs.run_sweep --base-url http://localhost:8000/v1 --model <model-id>
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from accessbench2.env import Environment
from accessbench2.families import build_tasks
from accessbench2.generate import build_corpus
from accessbench2.pdp import build_ladder
from accessbench2.scorer import RunReport, score_task
from docs.model_agent import OpenAICompatAgent, _StubModel


def sweep(agent, seed: int = 7):
    ladder = build_ladder()
    print(f"\nagent = {agent.name}")
    print(f"{'policy':<20}{'score':>8}{'acted':>8}{'refusal':>9}")
    print("-" * 45)
    for pdp in ladder:
        corpus = build_corpus(seed=seed)
        tasks = build_tasks(corpus)
        rep = RunReport(agent=agent.name, policy=pdp.name)
        acted = RunReport(agent=agent.name, policy=pdp.name)
        refused = 0
        for t in tasks:
            env = Environment(corpus, pdp)
            s = corpus.subjects[t["sub"]]
            res = agent.run(env, s, t)
            ts = score_task(corpus, env, t, res.final_answer)
            rep.scores.append(ts)
            if getattr(res, "refused", False):
                refused += 1
            else:
                acted.scores.append(ts)
        rr = refused / (len(tasks) or 1)
        acted_score = acted.score if acted.scores else 0.0
        print(f"{pdp.name:<20}{rep.score:>8.2f}{acted_score:>8.2f}{rr:>9.0%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--max-turns", type=int, default=8)
    a = ap.parse_args()
    if a.base_url and a.model:
        agent = OpenAICompatAgent(a.base_url, a.model, max_turns=a.max_turns)
    else:
        print("[no --base-url/--model given -> offline stub model]")
        agent = _StubModel()
    sweep(agent)


if __name__ == "__main__":
    main()
