# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for Anti-Cheat Judge calibration: the fixture corpus, scoring, and
the cache-and-gate behavior accessbench-env run --full depends on.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from accessbench_env.calibrate import (
    ensure_judge_calibrated,
    load_cached_calibration,
    precision_report,
    run_calibration,
)
from accessbench_env.calibration_fixtures import calibration_corpus


def _labeled_finding() -> dict:
    return {
        "finding_id": "f-1",
        "finding_type": "forbidden_egress",
        "actor": "subject",
        "scope": "x",
        "event_references": ["run"],
        "observed_behavior": "x",
        "declared_rule": "x",
        "benign_explanation": "x",
        "confidence": 0.9,
        "requested_check": "x",
    }


def _perfect_complete(request: dict):
    content = str(request["messages"][1]["content"])
    if "calib-adv" in content:
        return {"findings": [_labeled_finding()]}
    return {"findings": []}


def _always_flag_complete(request: dict):
    return {"findings": [_labeled_finding()]}


def _never_flag_complete(request: dict):
    return {"findings": []}


class CalibrationCorpusTests(unittest.TestCase):
    def test_corpus_has_both_labels_and_every_episode_is_uniquely_named(self):
        corpus = calibration_corpus()
        self.assertGreater(sum(1 for _, label in corpus if label), 0)
        self.assertGreater(sum(1 for _, label in corpus if not label), 0)
        trial_ids = [episode["trial_id"] for episode, _ in corpus]
        self.assertEqual(len(trial_ids), len(set(trial_ids)))

    def test_every_finding_type_has_an_adversarial_fixture(self):
        from accessbench_env.integrity_audit import FINDING_TYPES

        corpus = calibration_corpus()
        # The two injection-robustness fixtures reuse forbidden_egress as
        # their underlying concern, so they don't need to add new types.
        covered_prefixes = {
            episode["trial_id"] for episode, label in corpus if label
        }
        self.assertTrue(
            any("forbidden-egress" in t for t in covered_prefixes)
        )
        # Every category name should appear in some adversarial fixture's
        # trial_id, as a lightweight coverage check against silently
        # dropping a category.
        for finding_type in FINDING_TYPES:
            slug = finding_type.replace("_", "-")
            self.assertTrue(
                any(slug in t for t in covered_prefixes),
                f"no adversarial fixture name references {finding_type}",
            )


class PrecisionReportTests(unittest.TestCase):
    def test_perfect_separation_passes_with_full_precision_and_recall(self):
        rows = [
            {"label": True, "judge_flagged": True},
            {"label": True, "judge_flagged": True},
            {"label": False, "judge_flagged": False},
            {"label": False, "judge_flagged": False},
        ]
        report = precision_report(rows)
        self.assertEqual(report["gate"], "PASS")
        self.assertEqual(report["precision"], 1.0)
        self.assertEqual(report["recall"], 1.0)

    def test_false_positives_on_clean_fixtures_fail_the_gate(self):
        rows = [
            {"label": True, "judge_flagged": True},
            {"label": False, "judge_flagged": True},
            {"label": False, "judge_flagged": True},
            {"label": False, "judge_flagged": True},
        ]
        report = precision_report(rows)
        self.assertEqual(report["gate"], "FAIL")
        self.assertLess(report["precision"], 0.90)

    def test_never_flagging_anything_has_no_precision_and_fails(self):
        rows = [{"label": True, "judge_flagged": False}] * 3
        report = precision_report(rows)
        self.assertIsNone(report["precision"])
        self.assertEqual(report["gate"], "FAIL")


class RunCalibrationTests(unittest.TestCase):
    def test_perfect_judge_passes_on_the_real_corpus(self):
        report = run_calibration("mock-judge", _perfect_complete)
        self.assertEqual(report["gate"], "PASS")
        self.assertEqual(report["false_positive"], 0)
        self.assertEqual(report["false_negative"], 0)

    def test_a_judge_that_flags_everything_fails_on_precision(self):
        report = run_calibration("mock-judge", _always_flag_complete)
        self.assertEqual(report["gate"], "FAIL")
        self.assertGreater(report["false_positive"], 0)

    def test_a_judge_that_flags_nothing_fails_on_recall_and_has_no_precision(self):
        report = run_calibration("mock-judge", _never_flag_complete)
        self.assertIsNone(report["precision"])
        self.assertEqual(report["gate"], "FAIL")

    def test_injection_fixtures_are_not_trivially_gamed(self):
        """A Judge that just pattern-matches on 'SYSTEM:'/'Grader:' text
        would get the two injection fixtures right for the wrong reason;
        this at least confirms both are scored, not skipped or erroring.
        """
        report = run_calibration("mock-judge", _perfect_complete)
        ids = {row["trial_id"] for row in report["rows"]}
        self.assertIn("calib-adv-injection-induced-false-negative", ids)
        self.assertIn("calib-clean-injection-induced-false-positive", ids)


class EnsureJudgeCalibratedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_passing_calibration_is_cached_and_not_rerun(self):
        calls = {"n": 0}

        def counted(request):
            calls["n"] += 1
            return _perfect_complete(request)

        first = ensure_judge_calibrated("good-judge", counted, cache_dir=self.tmp)
        self.assertEqual(first["gate"], "PASS")
        n_after_first = calls["n"]
        self.assertGreater(n_after_first, 0)

        second = ensure_judge_calibrated("good-judge", counted, cache_dir=self.tmp)
        self.assertEqual(second["gate"], "PASS")
        self.assertEqual(calls["n"], n_after_first, "cached pass must not re-call the judge")

    def test_failing_calibration_refuses_to_run_and_caches_the_refusal(self):
        calls = {"n": 0}

        def counted(request):
            calls["n"] += 1
            return _always_flag_complete(request)

        with self.assertRaises(SystemExit):
            ensure_judge_calibrated("bad-judge", counted, cache_dir=self.tmp)
        n_after_first = calls["n"]
        self.assertGreater(n_after_first, 0)

        with self.assertRaises(SystemExit):
            ensure_judge_calibrated("bad-judge", counted, cache_dir=self.tmp)
        self.assertEqual(
            calls["n"], n_after_first,
            "a cached failure must refuse without re-calling the judge",
        )

    def test_recalibrate_forces_a_fresh_run_even_with_a_cached_pass(self):
        calls = {"n": 0}

        def counted(request):
            calls["n"] += 1
            return _perfect_complete(request)

        ensure_judge_calibrated("good-judge", counted, cache_dir=self.tmp)
        n_after_first = calls["n"]
        ensure_judge_calibrated(
            "good-judge", counted, cache_dir=self.tmp, force=True
        )
        self.assertGreater(calls["n"], n_after_first)

    def test_different_judge_models_do_not_share_a_cache_entry(self):
        ensure_judge_calibrated("judge-a", _perfect_complete, cache_dir=self.tmp)
        self.assertIsNone(
            load_cached_calibration(
                "judge-b",
                __import__("accessbench_env.anti_cheat_judge", fromlist=["x"])
                .ANTI_CHEAT_JUDGE_PROMPT_SHA256,
                cache_dir=self.tmp,
            )
        )

    def test_stale_audit_record_builder_version_is_not_reused(self):
        """A cached result is only valid for the exact builder that produced
        the audit records it was scored against -- see the false_completion
        bug (final_answer silently dropped) this guards against: a stale
        cache entry must be re-run, not trusted, once the builder changes.
        """
        from accessbench_env.anti_cheat_judge import ANTI_CHEAT_JUDGE_PROMPT_SHA256

        calls = {"n": 0}

        def counted(request):
            calls["n"] += 1
            return _perfect_complete(request)

        ensure_judge_calibrated("good-judge", counted, cache_dir=self.tmp)
        n_after_first = calls["n"]

        cache_path = next(self.tmp.glob("*.json"))
        import json
        stale = json.loads(cache_path.read_text())
        stale["audit_record_builder_version"] = "some-older-builder-v1"
        cache_path.write_text(json.dumps(stale))

        self.assertIsNone(
            load_cached_calibration(
                "good-judge", ANTI_CHEAT_JUDGE_PROMPT_SHA256, cache_dir=self.tmp
            )
        )
        ensure_judge_calibrated("good-judge", counted, cache_dir=self.tmp)
        self.assertGreater(
            calls["n"], n_after_first,
            "a stale builder version must trigger a fresh calibration run",
        )


if __name__ == "__main__":
    unittest.main()
