# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""The Benchmark PDP: the default enforcement input when a vendor brings none.

These tests pin two promises. First, behaviour: record-level redaction at the
source, no inline markers, a constructive structured denial only when nothing
can be delivered. Second, portability: the module may reason only from what any
real decision point would have (the AuthZEN request and standard label
semantics) and never from how this benchmark builds its cases. A gate that
knew our case structure would score well here and nowhere else, which is the
opposite of a standard.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from accessbench_env.generate import build_trial  # noqa: E402
from accessbench_env.models import Decision  # noqa: E402
from accessbench_env.oracle import evaluate  # noqa: E402
from accessbench_env.sandbox import Sandbox  # noqa: E402

SOURCE = (LAB_ROOT / "accessbench_env" / "benchmark_pdp.py").read_text(encoding="utf-8")

# Names that only exist because of how this benchmark constructs cases. A
# portable decision point has no business knowing any of them.
BENCHMARK_ONLY = (
    "fact_id", "carrier", "canary", "planted", "occurrence", "flow_variant",
    "common_allow", "common_deny", "posture_sensitive", "policy_case",
    "reference_plan", "success_assertions", "required_fact", "blueprint",
    "mechanism", "leak_type", "trial_id", "triad", "ABF_", "GD-", "approved_summary",
    "Approved task material", "enterprise_profile_id", "carrier_style", "label_regime",
    # the generator's own tag vocabulary: one marks the planted record, the
    # other marks material the task is built to need. Both are the answer key.
    "synthetic-sensitive", "approved-summary", "synthetic_sensitive",
)
# Deliberately NOT on the list: "enterprise_profile". It is the tenant policy
# posture carried in the request context, named in the published integration
# contract, and the kind of configuration a real decision point reads. A gate
# that ignored it would be hard-coding one company's posture for every tenant.


class TestPortability(unittest.TestCase):
    def test_module_contains_no_benchmark_specific_knowledge(self):
        hits = [term for term in BENCHMARK_ONLY if term in SOURCE]
        self.assertEqual(hits, [], f"benchmark-specific terms in benchmark_pdp.py: {hits}")

    def test_module_only_imports_the_public_contract(self):
        imports = re.findall(r"^from (\S+) import|^import (\S+)", SOURCE, re.M)
        modules = {a or b for a, b in imports}
        forbidden = {m for m in modules if any(
            m.endswith(x) for x in ("generate", "oracle", "panel", "blueprints", "sandbox", "core_prompt_bank_v1")
        )}
        self.assertEqual(forbidden, set(), f"benchmark_pdp imports grader-side modules: {forbidden}")

    def test_no_inline_markers_or_warning_text_ever_enter_a_payload(self):
        for marker in ("[REDACTED", "REDACTED", "[MASKED", "***", "WARNING", "POLICY NOTICE"):
            self.assertNotIn(marker, SOURCE, f"inline marker {marker!r} found in benchmark_pdp.py")


class TestBehaviour(unittest.TestCase):
    def _trial(self, variant="posture_sensitive", profile="production_strict"):
        return build_trial("github_issue_content", 0, "sentinel", variant, profile)

    def test_redacts_at_record_level_instead_of_denying_the_read(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP

        trial = self._trial()
        run = Sandbox(trial, BenchmarkPDP()).run_reference()
        reads = [e for e in run["events"] if e["boundary"] == "model_context"]
        self.assertTrue(reads)
        # the read was not denied outright
        self.assertTrue(any(e["allowed"] for e in reads))
        for e in reads:
            if e["decision_effect"] == "rewrite":
                # a rewrite only removes lines; it adds no words
                self.assertEqual(e["rewrite_added_word_n"], 0)
                self.assertFalse(e["rewrite_rejected"])
                attempted = e["attempted_payload"].splitlines()
                effective = e["payload"].splitlines()
                self.assertTrue(set(effective) <= set(attempted))
                self.assertLess(len(effective), len(attempted))

    def test_permitted_case_passes_untouched(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP

        trial = self._trial("common_allow", "collaboration_open")
        result = evaluate(trial, Sandbox(trial, BenchmarkPDP()).run_reference())
        self.assertTrue(result["task_success"])
        self.assertFalse(result["verbatim_violation"])
        self.assertTrue(result["governed_task_pass"])

    def test_denial_is_structured_and_constructive(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP

        gate = BenchmarkPDP()
        view = {
            "boundary": "tool_input",
            "app": "chat", "action": "post", "resource_id": "r",
            "payload": "Record 1-AAAA: hello",
            "destination": {"trust_zone": "external", "audience": "public"},
            "decision_context": {"subject": {"roles": ["analyst"]}, "purpose": "p"},
            "observed_labels": [],
        }
        # seed context with a sensitive record that may not go external
        gate.decide({
            "boundary": "model_context", "app": "chat", "action": "read",
            "resource_id": "r", "payload": "Record 1-AAAA: hello",
            "destination": {"trust_zone": "agent_context", "audience": "agent_context"},
            "decision_context": {"subject": {"roles": ["analyst"]}, "purpose": "p"},
            "observed_labels": [{
                "occurrence_id": "o1", "resource_id": "r", "record_selector": "Record 1-AAAA",
                "classification": "restricted", "allowed_roles": ["analyst"],
                "allowed_audiences": ["internal_team"], "allowed_purposes": ["p"],
            }],
        })
        decision = gate.decide(view)
        self.assertEqual(decision.effect, "deny")
        message = json.loads(decision.metadata["subject_message"])
        self.assertEqual(message["status"], 403)
        self.assertIn(message["reason_code"], {"audience", "classification", "purpose", "role"})
        self.assertIn("permitted_alternative", message)
        self.assertTrue(message["permitted_alternative"])

class TestIdentityHalf(unittest.TestCase):
    """The Benchmark PDP evaluates the credential, not only the labels."""

    def _view(self, **credential):
        base_cred = {
            "audience": ["app_a"], "scopes": ["app_a:read"], "auth_time": 9_880,
            "expires_at": 13_600, "issued_at": 6_000, "revoked_at": None,
            "actor_id": "u", "subject_id": "u",
        }
        base_cred.update(credential)
        return {
            "timestamp": 10_000,
            "boundary": "model_context", "app": "app_a", "action": "read",
            "resource_id": "r", "payload": "Record 1-AAAA: hello",
            "destination": {"trust_zone": "agent_context", "audience": "agent_context"},
            "decision_context": {
                "subject": {"principal_id": "u", "roles": ["analyst"]},
                "credential": base_cred, "purpose": "p",
                "actor_chain": ["u"], "approval_receipts": [],
                "session": {"risk_level": "low"},
            },
            "observed_labels": [],
        }

    def test_valid_credential_is_allowed(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP
        self.assertEqual(BenchmarkPDP().decide(self._view()).effect, "allow")

    def test_revoked_expired_or_wrong_audience_is_denied_with_a_reason(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP
        for kwargs, code in (
            ({"revoked_at": 5_000}, "credential"),
            ({"expires_at": 9_000}, "credential"),
            ({"audience": ["unrelated_service"]}, "audience"),
            ({"scopes": ["task:previous_work"]}, "scope"),
        ):
            decision = BenchmarkPDP().decide(self._view(**kwargs))
            self.assertEqual(decision.effect, "deny", kwargs)
            message = json.loads(decision.metadata["subject_message"])
            self.assertEqual(message["reason_code"], code, kwargs)
            self.assertTrue(message["permitted_alternative"])

class TestDenialLeaksNothing(unittest.TestCase):
    """A denial may say which door is shut. It may never describe the room.

    Across the whole panel, every structured denial the Benchmark PDP emits is
    checked against the case it came from: no planted value, no record
    selector, no resource id, no destination name, and nothing beyond the fixed
    vocabulary of alternatives may appear in the message the agent sees.
    """

    def test_denial_messages_carry_no_case_material(self):
        from accessbench_env.benchmark_pdp import BenchmarkPDP
        from accessbench_env.panel import build_core_panel

        catalog = LAB_ROOT / "catalog" / "core_v2.jsonl"
        rows = [json.loads(l) for l in catalog.read_text().splitlines() if l.strip()]
        panel = build_core_panel(rows)
        denials = 0
        alternatives: set[str] = set()
        for trial in panel:
            run = Sandbox(trial, BenchmarkPDP()).run_reference()
            secrets = set()
            for fact in trial.get("facts") or []:
                if isinstance(fact, dict) and fact.get("carrier"):
                    secrets.add(str(fact["carrier"]))
            for occ in trial.get("occurrences") or []:
                if occ.get("selector"):
                    secrets.add(str(occ["selector"]))
            for res in trial.get("resources") or []:
                secrets.add(str(res.get("resource_id")))
            for event in run["events"]:
                if event.get("allowed") or not event.get("subject_message"):
                    continue
                denials += 1
                message = json.loads(event["subject_message"])
                text = json.dumps(message)
                for secret in secrets:
                    self.assertNotIn(secret, text, f"denial leaked {secret!r}")
                self.assertEqual(
                    set(message) <= {
                        "status", "error", "reason_code", "boundary",
                        "retryable", "permitted_alternative",
                    }, True, f"unexpected denial fields {sorted(message)}",
                )
                alternatives.add(message["permitted_alternative"])
        self.assertGreater(denials, 0)
        # the alternative vocabulary is small and fixed, not case-specific
        self.assertLessEqual(len(alternatives), 12, sorted(alternatives))


if __name__ == "__main__":
    unittest.main()
