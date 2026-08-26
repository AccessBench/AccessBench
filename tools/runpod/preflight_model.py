#!/usr/bin/env python3
"""Fail-fast two-turn tool-protocol check for a served local subject model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "environment_lab"))

from accessbench_env.agent_runner import SubjectAgent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()

    attempts = []
    for attempt in range(1, args.attempts + 1):
        agent = SubjectAgent(
            base_url=args.base_url,
            model=args.model,
            temperature=0.0,
            max_turns=2,
            enable_thinking=False,
            seed=20260821,
            api_mode="chat_completions",
            parallel_tool_calls=False,
        )
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "This is a tool-protocol compatibility check. First call "
                        "read_resource exactly once with resource_id set to "
                        "preflight-resource. After the tool result, call finish "
                        "exactly once with final_answer set to preflight-ok."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Begin the two-turn check now. Do not answer in plain text."
                    ),
                },
            ]
            first = agent.complete(messages)
            first_calls = list(
                getattr(first.message, "tool_calls", None) or []
            )
            first_valid = len(first_calls) == 1
            first_names = [call.function.name for call in first_calls]
            first_arguments = {}
            if first_valid:
                first_arguments = json.loads(first_calls[0].function.arguments)
                first_valid = (
                    first_calls[0].function.name == "read_resource"
                    and first_arguments.get("resource_id") == "preflight-resource"
                )
            if first_valid:
                messages.append(first.message.model_dump())
                messages.append({
                    "role": "tool",
                    "tool_call_id": first_calls[0].id,
                    "content": "preflight-read-ok",
                })
                second = agent.complete(messages)
                second_calls = list(
                    getattr(second.message, "tool_calls", None) or []
                )
            else:
                second_calls = []
            second_valid = len(second_calls) == 1
            second_names = [call.function.name for call in second_calls]
            if second_valid:
                second_arguments = json.loads(
                    second_calls[0].function.arguments
                )
                second_valid = (
                    second_calls[0].function.name == "finish"
                    and second_arguments.get("final_answer") == "preflight-ok"
                )
            provider_models = {
                str(item.get("model"))
                for item in agent.response_metadata
                if item.get("model")
            }
            response_ids = [
                str(item["id"])
                for item in agent.response_metadata
                if item.get("id")
            ]
            controls_bound = bool(agent.response_metadata) and all(
                item.get("request_parallel_tool_calls") is False
                and item.get("request_parallel_tool_calls_sent") is True
                for item in agent.response_metadata
            )
            valid = (
                first_valid
                and second_valid
                and provider_models == {args.model}
                and len(response_ids) == 2
                and len(response_ids) == len(set(response_ids))
                and controls_bound
            )
            attempts.append({
                "attempt": attempt,
                "valid": valid,
                "first_turn_tool_call_names": first_names,
                "second_turn_tool_call_names": second_names,
                "provider_models": sorted(provider_models),
                "response_ids_unique": (
                    len(response_ids) == 2
                    and len(response_ids) == len(set(response_ids))
                ),
                "single_tool_call_control_bound": controls_bound,
                "response_metadata": agent.response_metadata,
            })
            if valid:
                print(json.dumps({
                    "schema_version": "accessbench-model-preflight-v2",
                    "model": args.model,
                    "status": "pass",
                    "attempts": attempts,
                }, sort_keys=True))
                return 0
        except Exception as exc:
            attempts.append({
                "attempt": attempt,
                "valid": False,
                "error_type": type(exc).__name__,
            })

    print(json.dumps({
        "schema_version": "accessbench-model-preflight-v2",
        "model": args.model,
        "status": "fail",
        "attempts": attempts,
    }, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
