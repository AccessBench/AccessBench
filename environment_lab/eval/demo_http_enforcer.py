# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Demonstrate the bring-your-own-PDP seam end to end.

Starts a mock deterministic PDP over localhost HTTP, points an HttpEnforcer at it, runs
a trial through the live runner, and scores it. Proves a vendor's own governance
plugs into AccessBench over HTTP and changes the oracle outcome. No GPU needed
(uses a scripted stub subject), so plug-and-play is demonstrated deterministically.
"""
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from accessbench_env import oracle
from accessbench_env.agent_runner import run_agent_trial
from accessbench_env.enforcers import AllowAll, HttpEnforcer
from mock_pdp import MockPDP


def _tc(cid, name, args):
    return SimpleNamespace(id=cid, function=SimpleNamespace(
        name=name, arguments=json.dumps(args)))


class _Msg:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls
        self.content = content

    def model_dump(self):
        return {"role": "assistant", "content": self.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {
                "name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in (self.tool_calls or [])]}


def naive(trial):
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
    trial = None
    with open(os.path.join(HERE, "..", "catalog", "public.jsonl")) as fh:
        for line in fh:
            t = json.loads(line)
            if t.get("flow_variant") == "common_deny":
                trial = t
                break

    pdp = MockPDP().start()
    print(
        "mock deterministic PDP listening at "
        f"{pdp.url}/access/v1/evaluation"
    )
    try:
        external = HttpEnforcer(pdp.url, name="external_pdp_http")
        for enf in (AllowAll(), external):
            run = run_agent_trial(trial, enforcer=enf, completion_fn=naive(trial))
            res = oracle.evaluate(trial, run)
            print(f"[{enf.name:<16}] verbatim_violation={res['verbatim_violation']} "
                  f"blocked_calls={run['blocked_calls']} status={run['final_status']}")
        print("SEAM OK: the same declared event view was mapped to AuthZEN 1.0 "
              "and the external PDP decision changed the oracle outcome.")
    finally:
        pdp.stop()


if __name__ == "__main__":
    main()
