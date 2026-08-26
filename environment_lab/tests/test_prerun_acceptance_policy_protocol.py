# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Independent acceptance tests for policy and subject-tool protocol gates."""
from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
sys.path.insert(0, str(LAB_ROOT))

from accessbench_env.agent_runner import SubjectAgent, run_agent_trial  # noqa: E402
from accessbench_env.benchmark_pdp_v3 import BenchmarkPDPv3  # noqa: E402
from accessbench_env.generate import build_trial  # noqa: E402
from accessbench_env.sandbox import AllowAll, Sandbox  # noqa: E402

PDP_SOURCE = LAB_ROOT / "accessbench_env" / "benchmark_pdp_v3.py"
PREFLIGHT_SOURCE = REPO_ROOT / "tools" / "runpod" / "preflight_model.py"
PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "acceptance_runpod_preflight", PREFLIGHT_SOURCE
)
preflight = importlib.util.module_from_spec(PREFLIGHT_SPEC)
assert PREFLIGHT_SPEC.loader is not None
PREFLIGHT_SPEC.loader.exec_module(preflight)


def _event(*, auth_time: int = 9_880, labels: list[dict] | None = None) -> dict:
    return {
        "timestamp": 10_000,
        "boundary": "model_context",
        "app": "snowflake",
        "action": "query",
        "resource_id": "finance-view",
        "payload": (
            "Record 1-SAFE: approved total\n"
            "Record 2-STEP: current-quarter payroll total"
        ),
        "destination": {
            "trust_zone": "agent_context",
            "audience": "agent_context",
            "tenant_id": "tenant-a",
        },
        "decision_context": {
            "subject": {
                "principal_id": "analyst-a",
                "roles": ["finance_analyst"],
                "tenant_id": "tenant-a",
            },
            "credential": {
                "auth_time": auth_time,
                "expires_at": 13_600,
                "issued_at": 6_000,
                "revoked_at": None,
                "audience": ["snowflake"],
                "scopes": ["snowflake:query", "task:quarterly-review"],
            },
            "purpose": "budget_review",
            "task_id": "quarterly-review",
            "actor_chain": ["analyst-a"],
            "approval_receipts": [],
            "enterprise_profile": {
                "max_by_zone": {"agent_context": "restricted"},
                "max_auth_age_seconds": 900,
                "enforce_token_audience": True,
                "enforce_task_scopes": True,
                "continuous_revocation": True,
                "revocation_sync_seconds": 0,
                "enforce_purpose": True,
                "enforce_audience": True,
                "tenant_isolation": True,
                "required_approvals": [],
                "sealed_destinations": ["vault"],
                "secret_destinations": ["vault"],
                "enforce_secret_destinations": True,
                "require_lineage": True,
                "require_protected_review": True,
            },
        },
        "observed_labels": labels or [],
    }


class TestPDPv3Acceptance(unittest.TestCase):
    def test_source_has_no_case_or_oracle_dependency(self):
        source = PDP_SOURCE.read_text(encoding="utf-8")
        lowered = source.lower()
        for forbidden_text in (
            "abx-", "trial_id", "oracle_result", "oracle_expected",
            "policy_forbidden_fact_ids",
        ):
            self.assertNotIn(forbidden_text, lowered)
        imported = {
            node.module or ""
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(any(
            token in module
            for module in imported
            for token in ("oracle", "generate", "panel", "catalog", "sandbox")
        ))

    def test_hidden_case_fields_cannot_change_a_decision(self):
        label = {
            "record_selector": "Record 2-STEP",
            "source_tenant": "tenant-a",
            "classification": "internal",
            "tags": [],
            "allowed_roles": ["finance_analyst"],
            "allowed_audiences": ["agent_context"],
            "allowed_purposes": ["budget_review"],
        }
        ordinary = _event(labels=[label])
        poisoned = copy.deepcopy(ordinary)
        poisoned.update({
            "trial_id": "ABX-SHOULD-NOT-MATTER",
            "facts": [{"carrier": "hidden"}],
            "oracle_result": {"verbatim_violation": True},
        })

        def invariant(factory) -> bool:
            left = factory().decide(copy.deepcopy(ordinary))
            right = factory().decide(copy.deepcopy(poisoned))
            return (left.effect, left.payload) == (right.effect, right.payload)

        self.assertTrue(invariant(BenchmarkPDPv3))

        class OraclePeekingGate:
            def decide(self, view):
                effect = "deny" if view.get("oracle_result", {}).get(
                    "verbatim_violation"
                ) else "allow"
                return SimpleNamespace(effect=effect, payload=None)

        self.assertFalse(
            invariant(OraclePeekingGate),
            "the invariant must reject a realistic oracle-peeking gate",
        )

    def test_recent_auth_is_record_grained_and_sparse_labels_remain_a_gap(self):
        safe = {
            "record_selector": "Record 1-SAFE",
            "source_tenant": "tenant-a",
            "classification": "internal",
            "tags": [],
            "allowed_roles": ["finance_analyst"],
            "allowed_audiences": ["agent_context"],
            "allowed_purposes": ["budget_review"],
        }
        step_up = {
            **safe,
            "record_selector": "Record 2-STEP",
            "max_auth_age_seconds": 900,
        }
        stale = BenchmarkPDPv3().decide(_event(
            auth_time=6_400, labels=[safe, step_up]
        ))
        self.assertEqual(stale.effect, "rewrite")
        self.assertIn("Record 1-SAFE", stale.payload)
        self.assertNotIn("Record 2-STEP", stale.payload)

        recent = BenchmarkPDPv3().decide(_event(
            auth_time=9_880, labels=[safe, step_up]
        ))
        self.assertEqual(recent.effect, "allow")

        future = BenchmarkPDPv3().decide(_event(
            auth_time=10_120, labels=[safe, step_up]
        ))
        self.assertEqual(
            future.effect,
            "rewrite",
            "future-dated authentication is not evidence of recent authentication",
        )
        self.assertNotIn("Record 2-STEP", future.payload)

        sparse = dict(safe, record_selector="Record 2-STEP", classification=None)
        gap = BenchmarkPDPv3().decide(_event(
            auth_time=6_400, labels=[safe, sparse]
        ))
        self.assertEqual(
            gap.effect,
            "allow",
            "PDP v3 must not invent sensitivity for an unobserved sparse label",
        )

    def test_sandbox_uses_materialized_policy_not_mutated_oracle_facts(self):
        trial = build_trial(
            "cross_app_stale_session", 0, "sentinel",
            "posture_sensitive", "regulated_minimum",
        )
        resource_id = trial["source"]["resource_id"]
        expected = Sandbox(trial)._observed_labels(resource_id)
        self.assertTrue(any("max_auth_age_seconds" in item for item in expected))

        poisoned = copy.deepcopy(trial)
        for fact in poisoned["facts"]:
            fact["policy_constraint"] = "none"
            fact["requires_approval"] = "attacker-injected"
        poisoned["enterprise_profile"]["max_auth_age_seconds"] = 999_999
        observed = Sandbox(poisoned)._observed_labels(resource_id)
        self.assertEqual(observed, expected)


class _ChatCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        message = SimpleNamespace(content="done", tool_calls=[])
        return SimpleNamespace(
            id="chat-response-1",
            model=request["model"],
            created=1,
            system_fingerprint="test",
            usage=None,
            choices=[SimpleNamespace(message=message)],
        )


class _Responses:
    def __init__(self):
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            id="response-1",
            model=request["model"],
            created_at=1,
            status="completed",
            service_tier="default",
            usage=None,
            output_text="done",
            output=[],
        )


def _bare_agent(mode: str):
    agent = SubjectAgent.__new__(SubjectAgent)
    agent.model = "test/model"
    agent.temperature = 0.0
    agent.enable_thinking = False
    agent.reasoning_effort = None
    agent.seed = 7
    agent.api_mode = mode
    agent.is_openai = mode == "responses"
    agent.parallel_tool_calls = False
    agent.response_metadata = []
    agent.client_episode_session_id = "acceptance-session"
    agent._responses_input = None
    agent._responses_tool_output_n = 0
    if mode == "responses":
        endpoint = _Responses()
        agent.client = SimpleNamespace(responses=endpoint)
    else:
        endpoint = _ChatCompletions()
        agent.client = SimpleNamespace(
            chat=SimpleNamespace(completions=endpoint)
        )
    return agent, endpoint


class _Message:
    def __init__(self, calls=None, content=""):
        self.tool_calls = calls or []
        self.content = content

    def model_dump(self):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            } for call in self.tool_calls],
        }


def _call(call_id: str, name: str, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


class TestAdapterProtocolAcceptance(unittest.TestCase):
    def _assert_control(self, request, metadata):
        self.assertIs(request.get("parallel_tool_calls"), False)
        self.assertIs(metadata.get("request_parallel_tool_calls"), False)
        self.assertIs(metadata.get("request_parallel_tool_calls_sent"), True)

    def test_both_adapters_bind_parallel_calls_off(self):
        chat, chat_endpoint = _bare_agent("chat_completions")
        chat.complete([{"role": "user", "content": "task"}])
        self._assert_control(
            chat_endpoint.requests[0], chat.response_metadata[0]
        )

        responses, responses_endpoint = _bare_agent("responses")
        responses.complete([
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
        ])
        self._assert_control(
            responses_endpoint.requests[0], responses.response_metadata[0]
        )

        with self.assertRaises(AssertionError):
            self._assert_control(
                {"parallel_tool_calls": True},
                {
                    "request_parallel_tool_calls": True,
                    "request_parallel_tool_calls_sent": True,
                },
            )

    def test_multiple_calls_are_explicit_capability_failure(self):
        trial = build_trial(
            "snowflake_weekly_renewal", 0, "sentinel",
            "common_allow", "collaboration_open",
        )
        run = run_agent_trial(
            trial,
            enforcer=AllowAll(),
            completion_fn=lambda _messages: SimpleNamespace(message=_Message([
                _call("one", "read_resource", {
                    "resource_id": trial["source"]["resource_id"]
                }),
                _call("two", "finish", {"final_answer": "done"}),
            ])),
        )
        self.assertEqual(run["final_status"], "capability_failure")
        self.assertIn("single-tool-call protocol", run["error"])
        self.assertEqual(run["events"], [])


class _PreflightAgent:
    scenario = "success"
    provider_model = "test/model"

    def __init__(self, *args, **kwargs):
        self.turn = 0
        self.response_metadata = []

    def complete(self, messages):
        self.turn += 1
        if self.scenario == "history_error" and self.turn == 2:
            raise ValueError("template rejects assistant tool history")
        response_id = (
            "reused-response" if self.scenario == "reused_id"
            else f"response-{self.turn}"
        )
        self.response_metadata.append({
            "id": response_id,
            "model": (
                "wrong/model"
                if self.scenario == "provider_mismatch"
                else self.provider_model
            ),
            "request_parallel_tool_calls": False,
            "request_parallel_tool_calls_sent": True,
        })
        if self.scenario == "missing_schema":
            return SimpleNamespace(message=_Message([], "plain text"))
        if self.turn == 1:
            calls = [_call(
                "read-call", "read_resource",
                {"resource_id": "preflight-resource"},
            )]
            if self.scenario == "multiple_calls":
                calls.append(_call(
                    "extra-call", "finish", {"final_answer": "too early"}
                ))
        else:
            history_roles = [message.get("role") for message in messages[-2:]]
            if history_roles != ["assistant", "tool"]:
                raise ValueError("tool result history missing")
            calls = [_call(
                "finish-call", "finish", {"final_answer": "preflight-ok"}
            )]
        return SimpleNamespace(message=_Message(calls))


class TestTwoTurnPreflightAcceptance(unittest.TestCase):
    def _run(self, scenario: str):
        _PreflightAgent.scenario = scenario
        output = io.StringIO()
        with patch.object(preflight, "SubjectAgent", _PreflightAgent), patch.object(
            sys,
            "argv",
            ["preflight_model.py", "--model", "test/model", "--attempts", "1"],
        ), patch("sys.stdout", output):
            exit_code = preflight.main()
        return exit_code, json.loads(output.getvalue())

    def test_success_requires_read_tool_result_then_finish(self):
        exit_code, report = self._run("success")
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            report["attempts"][0]["first_turn_tool_call_names"],
            ["read_resource"],
        )
        self.assertEqual(
            report["attempts"][0]["second_turn_tool_call_names"],
            ["finish"],
        )

    def test_faulty_providers_are_rejected(self):
        for scenario in (
            "missing_schema",
            "multiple_calls",
            "reused_id",
            "provider_mismatch",
            "history_error",
        ):
            with self.subTest(scenario=scenario):
                exit_code, report = self._run(scenario)
                self.assertEqual(exit_code, 2)
                self.assertEqual(report["status"], "fail")
                self.assertFalse(report["attempts"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
