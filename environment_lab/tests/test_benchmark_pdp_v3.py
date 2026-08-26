# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Contract tests for the record-policy-aware Benchmark PDP v3."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from accessbench_env.benchmark_pdp_v2 import BenchmarkPDPv2  # noqa: E402
from accessbench_env.benchmark_pdp_v3 import BenchmarkPDPv3  # noqa: E402
from accessbench_env.generate import build_trial  # noqa: E402
from accessbench_env.oracle import evaluate  # noqa: E402
from accessbench_env.panel import build_core_panel  # noqa: E402
from accessbench_env.sandbox import Sandbox  # noqa: E402
from tests.test_benchmark_pdp import BENCHMARK_ONLY  # noqa: E402
from tests.test_benchmark_pdp_v2 import L1, STRICT, TWO, _view  # noqa: E402

SOURCE = (LAB_ROOT / "accessbench_env" / "benchmark_pdp_v3.py").read_text(
    encoding="utf-8"
)


class TestPortability(unittest.TestCase):
    def test_module_contains_no_benchmark_specific_knowledge(self):
        hits = [term for term in BENCHMARK_ONLY if term in SOURCE]
        self.assertEqual(hits, [], f"benchmark-specific terms in PDP v3: {hits}")

    def test_module_imports_no_generator_or_grader(self):
        imports = re.findall(r"^from (\S+) import|^import (\S+)", SOURCE, re.M)
        modules = {left or right for left, right in imports}
        forbidden = {
            module for module in modules
            if any(name in module for name in (
                "generate", "oracle", "panel", "blueprints", "sandbox", "catalog"
            ))
        }
        self.assertEqual(forbidden, set())


class TestRecordAuthPolicy(unittest.TestCase):
    def test_record_auth_age_is_independent_of_classification(self):
        label = dict(L1, classification="internal", max_auth_age_seconds=900)
        view = _view(
            "model_context",
            labels=[label],
            profile=STRICT,
            credential={"auth_time": 6_400},
        )
        self.assertEqual(BenchmarkPDPv2().decide(view).effect, "allow")
        decision = BenchmarkPDPv3().decide(view)
        self.assertEqual(decision.effect, "deny")
        self.assertEqual(decision.metadata["reason_code"], "credential")

    def test_only_the_stale_constrained_record_is_removed(self):
        constrained = dict(
            L1,
            record_selector="Record 2-BBBB",
            classification="internal",
            max_auth_age_seconds=900,
        )
        decision = BenchmarkPDPv3().decide(_view(
            "model_context",
            labels=[L1, constrained],
            payload=TWO,
            profile=STRICT,
            credential={"auth_time": 6_400},
        ))
        self.assertEqual(decision.effect, "rewrite")
        self.assertIn("Record 1-AAAA", decision.payload)
        self.assertNotIn("Record 2-BBBB", decision.payload)

    def test_recent_authentication_allows_the_record(self):
        label = dict(L1, max_auth_age_seconds=900)
        decision = BenchmarkPDPv3().decide(_view(
            "model_context",
            labels=[label],
            profile=STRICT,
            credential={"auth_time": 9_880},
        ))
        self.assertEqual(decision.effect, "allow")

    def test_sandbox_exposes_policy_only_on_constrained_record(self):
        trial = build_trial(
            "cross_app_stale_session",
            0,
            "sentinel",
            "posture_sensitive",
            "regulated_minimum",
        )
        labels = Sandbox(trial)._observed_labels(trial["source"]["resource_id"])
        policy_facts = {
            fact["fact_id"]
            for fact in trial["facts"]
            if fact["policy_constraint"] == "auth_age"
        }
        expected_selectors = {
            occurrence["selector"]
            for occurrence in trial["occurrences"]
            if occurrence["fact_id"] in policy_facts
        }
        observed_selectors = {
            label["record_selector"]
            for label in labels
            if "max_auth_age_seconds" in label
        }
        self.assertEqual(observed_selectors, expected_selectors)
        self.assertTrue(all(
            label["max_auth_age_seconds"] == 900
            for label in labels
            if "max_auth_age_seconds" in label
        ))

    def test_full_panel_has_no_recent_auth_policy_leak(self):
        rows = [
            json.loads(line)
            for line in (LAB_ROOT / "catalog" / "core_v2.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        constrained = [
            trial for trial in build_core_panel(rows)
            if any(
                fact.get("policy_constraint") == "auth_age"
                for fact in trial["facts"]
            )
        ]
        self.assertTrue(constrained)
        for trial in constrained:
            result = evaluate(
                trial,
                Sandbox(trial, BenchmarkPDPv3()).run_reference(),
            )
            with self.subTest(trial_id=trial["trial_id"]):
                self.assertFalse(result["verbatim_violation"])


class TestFailClosedSchema(unittest.TestCase):
    def test_absent_classification_remains_a_valid_sparse_label(self):
        label = dict(L1)
        label.pop("classification")
        decision = BenchmarkPDPv3().decide(_view(
            "model_context", labels=[label], profile=STRICT
        ))
        self.assertEqual(decision.effect, "allow")

    def test_unknown_classification_is_denied_not_treated_as_absent(self):
        label = dict(L1, classification="top-secret-plus")
        decision = BenchmarkPDPv3().decide(_view(
            "model_context", labels=[label], profile=STRICT
        ))
        self.assertEqual(decision.effect, "deny")
        self.assertEqual(decision.metadata["reason_code"], "scope")

    def test_unknown_boundary_and_malformed_claims_fail_closed(self):
        for mutation in (
            {"boundary": "unknown"},
            {"observed_labels": None},
            {"decision_context": {"subject": {"roles": "analyst"}}},
        ):
            view = _view("model_context", profile=STRICT)
            view.update(mutation)
            with self.subTest(mutation=mutation):
                self.assertEqual(BenchmarkPDPv3().decide(view).effect, "deny")


if __name__ == "__main__":
    unittest.main()
