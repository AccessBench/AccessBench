# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Regression tests for the live subject-agent runner.

The load-bearing guarantee: the model sees only agent_view. No oracle-only field
(facts, carriers, fact/occurrence ids, reference_plan, success_assertions,
enterprise_profile, defense_view, triad/flow polarity) may reach the model.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "..", "catalog", "public.jsonl")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accessbench_env import oracle
from accessbench_env.agent_runner import agent_view, run_agent_trial
from accessbench_env.enforcers import AllowAll, LabelGovernance
from accessbench_env.generate import build_trial


def _load_trials(n=25):
    out = []
    with open(CATALOG) as fh:
        for line in fh:
            out.append(json.loads(line))
            if len(out) >= n:
                break
    return out


FORBIDDEN_KEYS = {
    "facts", "occurrences", "reference_plan", "success_assertions",
    "oracle_expected", "enterprise_profile", "defense_view", "flow_variant",
    "triad_id", "posture_counterfactual_id", "mechanism", "headroom",
    "seed_commitment",
}


class TestAgentViewLeakage(unittest.TestCase):
    def test_no_oracle_only_keys_or_values_reach_model(self):
        for trial in _load_trials():
            view = agent_view(trial)
            blob = json.dumps(view)
            # no oracle-only top-level keys anywhere in the view
            for key in FORBIDDEN_KEYS:
                self.assertNotIn(f'"{key}"', blob,
                                 f"{key} leaked into agent_view of {trial['trial_id']}")
            # no fact ids, occurrence ids, or carriers
            for fact in trial["facts"]:
                self.assertNotIn(fact["fact_id"], blob, "fact_id leaked")
                if fact.get("carrier"):
                    self.assertNotIn(fact["carrier"], blob, "carrier leaked into view")
            for occ in trial["occurrences"]:
                self.assertNotIn(occ["occurrence_id"], blob, "occurrence_id leaked")
            # polarity must not leak
            self.assertNotIn(str(trial.get("flow_variant")), blob)

    def test_view_has_the_agent_visible_essentials(self):
        view = agent_view(_load_trials(1)[0])
        for key in ("task", "purpose", "source", "destination", "identity",
                    "available_resources"):
            self.assertIn(key, view)
        self.assertIn("requester", view["identity"])


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


class TestRunnerContract(unittest.TestCase):
    def _naive(self, trial):
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

    def test_run_is_oracle_ready_and_enforcer_matters(self):
        # a common_deny trial: no governance leaks, governance contains
        trial = next(t for t in _load_trials(200)
                     if t.get("flow_variant") == "common_deny")
        open_run = run_agent_trial(trial, enforcer=AllowAll(),
                                   completion_fn=self._naive(trial))
        gov_run = run_agent_trial(trial, enforcer=LabelGovernance(),
                                  completion_fn=self._naive(trial))
        for run in (open_run, gov_run):
            for key in ("trial_id", "enforcer", "events", "final_status",
                        "blocked_calls", "subject_trace"):
                self.assertIn(key, run)
            self.assertTrue(any(
                item["kind"] == "assistant" for item in run["subject_trace"]
            ))
            self.assertTrue(any(
                item["kind"] == "tool_result" for item in run["subject_trace"]
            ))
            self.assertEqual(
                len({item["trace_reference"] for item in run["subject_trace"]}),
                len(run["subject_trace"]),
            )
        open_res = oracle.evaluate(trial, open_run)
        gov_res = oracle.evaluate(trial, gov_run)
        self.assertTrue(open_res["verbatim_violation"], "control should leak")
        self.assertFalse(gov_res["verbatim_violation"], "governance should contain")

    def test_agent_can_minimize_adjacent_material(self):
        trial = build_trial(
            "salesforce_discount_export", 0, "sentinel",
            "posture_sensitive", "regulated_minimum",
        )
        src = trial["source"]["resource_id"]
        fact_by_id = {fact["fact_id"]: fact for fact in trial["facts"]}
        occurrence_by_fact = {
            occurrence["fact_id"]: occurrence for occurrence in trial["occurrences"]
        }
        required_lines = [trial["task_contract"]["artifact_title"]]
        for fact_id in trial["success_assertions"]["required_fact_ids"]:
            required_lines.append(
                f"{occurrence_by_fact[fact_id]['selector']}: "
                f"{fact_by_id[fact_id]['carrier']}"
            )
        required = "\n".join(required_lines)
        steps = iter([
            _Msg(tool_calls=[_tc("c1", "read_resource", {"resource_id": src})]),
            _Msg(tool_calls=[_tc(
                "c2", "deliver_to_destination", {"content": required}
            )]),
            _Msg(content="Done."),
        ])
        run = run_agent_trial(
            trial,
            enforcer=AllowAll(),
            completion_fn=lambda _m: SimpleNamespace(message=next(steps)),
        )
        result = oracle.evaluate(trial, run)
        self.assertTrue(result["task_success"])
        self.assertFalse(result["verbatim_violation"])

    def test_live_runner_uses_native_resource_actions(self):
        cases = (
            ("slack_vendor_thread", "read_thread", "create_issue_comment"),
            ("github_hotfix_branch", "read_file", "create_pull_request"),
            ("drive_partner_link", "read_document", "share_document"),
            ("salesforce_partner_book", "search_records", "post_message"),
        )
        for blueprint_id, read_action, write_action in cases:
            trial = build_trial(
                blueprint_id, 0, "sentinel", "common_allow",
                "collaboration_open",
            )
            run = run_agent_trial(
                trial, enforcer=AllowAll(), completion_fn=self._naive(trial)
            )
            model_reads = [
                e for e in run["events"] if e["boundary"] == "model_context"
            ]
            commits = [e for e in run["events"] if e["boundary"] == "app_commit"]
            self.assertEqual(model_reads[-1]["action"], read_action)
            self.assertEqual(commits[-1]["action"], write_action)

    def test_clean_nondelivery_is_abandoned(self):
        trial = build_trial(
            "snowflake_weekly_renewal", 0, "sentinel",
            "common_allow", "collaboration_open",
        )
        run = run_agent_trial(
            trial,
            enforcer=AllowAll(),
            completion_fn=lambda _m: SimpleNamespace(message=_Msg(content="Done.")),
        )
        self.assertEqual(run["final_status"], "abandoned")
        self.assertFalse(run["delivered"])

    def test_multiple_tool_calls_in_one_turn_are_a_capability_failure(self):
        trial = build_trial(
            "snowflake_weekly_renewal", 0, "sentinel",
            "common_allow", "collaboration_open",
        )
        source = trial["source"]["resource_id"]
        run = run_agent_trial(
            trial,
            enforcer=AllowAll(),
            completion_fn=lambda _messages: SimpleNamespace(message=_Msg(
                tool_calls=[
                    _tc("c1", "read_resource", {"resource_id": source}),
                    _tc("c2", "finish", {"final_answer": "done"}),
                ]
            )),
        )
        self.assertEqual(run["final_status"], "capability_failure")
        self.assertIn("single-tool-call protocol", run["error"])
        self.assertEqual(run["events"], [])


class ClientSideFailureTests(unittest.TestCase):
    """A crash on our side before any provider response is not model behavior."""

    def _trial(self):
        return build_trial(
            "snowflake_weekly_renewal", 0, "sentinel",
            "common_allow", "collaboration_open",
        )

    def test_exception_before_any_provider_response_routes_to_transport(self):
        from accessbench_env.agent_runner import ClientSideFailure, is_transport_failure

        class _CrashesBeforeAnswering:
            name = "crashy"
            max_turns = 8
            response_metadata: list = []

            def complete(self, _messages):
                raise TypeError("BaseModel cannot be instantiated directly")

        with self.assertRaises(ClientSideFailure) as stop:
            run_agent_trial(self._trial(), enforcer=AllowAll(), agent=_CrashesBeforeAnswering())
        self.assertTrue(is_transport_failure(stop.exception))
        self.assertIn("before any provider response", str(stop.exception))
        self.assertIn("BaseModel cannot be instantiated", str(stop.exception))

    def test_exception_after_a_provider_response_is_still_capability_failure(self):
        class _AnswersThenCrashes:
            name = "flaky"
            max_turns = 8

            def __init__(self):
                self.response_metadata = []

            def complete(self, _messages):
                if not self.response_metadata:
                    self.response_metadata.append({"id": "resp-1"})
                    return SimpleNamespace(message=_Msg(tool_calls=[
                        _tc("c1", "read_resource", {"resource_id": "nothing"}),
                    ]))
                raise TypeError("broke on the second turn")

        run = run_agent_trial(self._trial(), enforcer=AllowAll(), agent=_AnswersThenCrashes())
        self.assertEqual(run["final_status"], "capability_failure")
        self.assertIn("broke on the second turn", run["error"])


if __name__ == "__main__":
    unittest.main()
