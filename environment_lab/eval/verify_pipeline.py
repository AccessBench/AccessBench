# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Deterministic pipeline check: runner -> enforcer -> oracle, no GPU.

A scripted stub agent (read source, deliver to destination) proves the live
runner wiring and that the enforcer changes the oracle outcome, before any
model inference is spent.
"""
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # environment_lab on path

from accessbench_env import oracle
from accessbench_env.agent_runner import run_agent_trial
from accessbench_env.enforcers import AllowAll, ConnectionGovernance, LabelGovernance


def _tc(cid, name, args):
    return SimpleNamespace(id=cid, function=SimpleNamespace(
        name=name, arguments=json.dumps(args)))


class _Msg:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls
        self.content = content

    def model_dump(self):
        return {"role": "assistant", "content": self.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in (self.tool_calls or [])]}


def naive_stub(trial):
    """Reads the task source and delivers it onward. The floor agent."""
    src = trial["source"]["resource_id"]
    turn = {"n": 0}

    def complete(messages):
        turn["n"] += 1
        if turn["n"] == 1:
            msg = _Msg(tool_calls=[_tc(
                "c1", "read_resource", {"resource_id": src}
            )])
        elif turn["n"] == 2:
            msg = _Msg(tool_calls=[_tc(
                "c2", "deliver_to_destination",
                {"content": messages[-1]["content"]},
            )])
        else:
            msg = _Msg(content="Done.")
        return SimpleNamespace(message=msg)
    return complete


def main():
    catalog = os.path.join(HERE, "..", "catalog", "public.jsonl")
    # scan for one trial of each flow polarity to show the enforcer mattering
    picks = {}
    with open(catalog) as fh:
        for line in fh:
            t = json.loads(line)
            fv = t.get("flow_variant")
            if fv not in picks:
                picks[fv] = t
            if len(picks) >= 3:
                break
    print(f"{'flow_variant':<18}{'enforcer':<18}{'status':<12}{'deliver':<8}"
          f"{'verbatim_viol':<15}{'task_ok':<9}{'blocked'}")
    print("-" * 88)
    for fv, trial in picks.items():
        for enf_cls in (AllowAll, ConnectionGovernance, LabelGovernance):
            run = run_agent_trial(trial, enforcer=enf_cls(),
                                  completion_fn=naive_stub(trial))
            res = oracle.evaluate(trial, run)
            print(f"{fv:<18}{enf_cls().name:<18}{run['final_status']:<12}"
                  f"{str(run['delivered']):<8}{str(res['verbatim_violation']):<15}"
                  f"{str(res['task_success']):<9}{run['blocked_calls']}")
        print()


if __name__ == "__main__":
    main()
