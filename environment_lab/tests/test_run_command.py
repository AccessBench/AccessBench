# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for `accessbench-env run`, the orchestrating entry point.

The subject agent is replaced by the deterministic reference path, matching
test_run_eval_smoke_resume.py, so no model call happens. These tests cover
the orchestration behavior (defaults, sequencing, signing-key bootstrap) and
deliberately do not re-test run_eval.py/aggregate.py internals, which already
have their own tests.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(LAB_ROOT / "eval"))

import run_eval  # noqa: E402
from accessbench_env import cli, run_command  # noqa: E402
from accessbench_env.sandbox import Sandbox  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
from io import StringIO  # noqa: E402


class _DummyAgent:
    def __init__(self, *a, **k):
        self.client_episode_session_id = os.urandom(8).hex()
        self.response_metadata = [{
            "api_mode": "chat_completions",
            "id": f"resp-{os.urandom(4).hex()}",
            "model": k.get("model", "dummy"),
            "request_temperature": k.get("temperature", 0.0),
            "request_temperature_sent": True,
            "request_seed": k.get("seed"),
            "request_seed_sent": True,
            "request_enable_thinking": k.get("enable_thinking", False),
            "request_enable_thinking_sent": False,
            "reasoning_effort": k.get("reasoning_effort"),
            "request_reasoning_sent": False,
            "client_episode_session_id": self.client_episode_session_id,
            "request_parallel_tool_calls": k.get(
                "parallel_tool_calls", False
            ),
            "request_parallel_tool_calls_sent": True,
        }]


def _reference_run(trial, enforcer=None, agent=None, completion_fn=None):
    run = Sandbox(trial, enforcer).run_reference()
    run.update({
        "delivered": run["final_status"] == "completed",
        "delivery_attempted": True,
        "blocked_delivery": run["blocked_calls"] > 0,
        "subject_trace": [],
        "model_responses": list(agent.response_metadata) if agent else [],
    })
    return run


def _trust_anti_cheat_key(signing_key_path: str) -> None:
    """Test-only stand-in for a committed TRUSTED_KEYS.json entry: sets the
    additive env-var override so a sidecar signed by this key reads as
    trusted, without touching the real registry file.
    """
    from accessbench_env.evidence import load_signing_key, public_key_id

    key_id = public_key_id(load_signing_key(signing_key_path).public_key())
    os.environ["ACCESSBENCH_TRUSTED_ANTI_CHEAT_KEY_IDS"] = key_id


class TestCommandRunOffline(unittest.TestCase):
    def test_no_model_or_enforcement_is_free_and_prints_next_step(self):
        args = cli.parser().parse_args(["run"])
        with patch("builtins.print") as printed:
            cli.command_run(args)
        messages = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("--model MODEL --enforcement ENFORCEMENT", messages)

    def test_model_without_enforcement_is_rejected(self):
        args = cli.parser().parse_args(["run", "--model", "m"])
        with self.assertRaises(SystemExit):
            cli.command_run(args)


class TestCalibrationGate(unittest.TestCase):
    """A failed calibration must block --full before the real (paid) run
    starts, not just before the Judge pass at the end.
    """

    def test_failed_calibration_blocks_before_any_real_run(self):
        args = cli.parser().parse_args([
            "run", "--model", "m", "--enforcement", "label_governance", "--full",
        ])
        with patch.object(
            run_command, "ensure_judge_calibrated_for_run",
            side_effect=SystemExit("calibration failed"),
        ) as calibrate_mock, \
             patch.object(
                 run_command, "resolve_enforcement_arg",
                 return_value=("label_governance", None),
             ), \
             patch.object(run_command, "print_spend_estimate"), \
             patch.object(run_command, "preflight", return_value="/tmp/key.pem"), \
             patch.object(run_command, "run_eval_arm") as run_eval_arm_mock:
            with self.assertRaises(SystemExit):
                cli.command_run(args)
        calibrate_mock.assert_called_once()
        run_eval_arm_mock.assert_not_called()

    def test_passed_calibration_report_is_threaded_into_run_integrity_audit(self):
        args = cli.parser().parse_args([
            "run", "--model", "m", "--enforcement", "label_governance", "--full",
        ])
        report = {"gate": "PASS", "precision": 1.0, "n": 24}
        with patch.object(
            run_command, "ensure_judge_calibrated_for_run", return_value=report
        ), \
             patch.object(
                 run_command, "resolve_enforcement_arg",
                 return_value=("label_governance", None),
             ), \
             patch.object(run_command, "print_spend_estimate"), \
             patch.object(run_command, "preflight", return_value="/tmp/key.pem"), \
             patch.object(run_command, "check_signing_key_trust"), \
             patch.object(run_command, "snapshot_raws", return_value=set()), \
             patch.object(run_command, "snapshot_results", return_value=set()), \
             patch.object(run_command, "run_eval_arm", return_value=Path("/tmp/raw.jsonl")), \
             patch.object(run_command, "run_integrity_audit") as audit_mock, \
             patch.object(
                 run_command, "aggregate_raw", return_value=run_command.RESULTS_ROOT
             ), \
             patch.object(
                 run_command, "find_new_result_dir", return_value=Path("/tmp/result-dir"),
             ), \
             patch.object(
                 run_command, "build_bundle",
                 return_value={"bundle": Path("/tmp/bundle"), "report": Path("/tmp/report.html")},
             ), \
             patch.object(run_command, "dashboard_hint", return_value=("cmd", "url")):
            cli.command_run(args)
        _, kwargs = audit_mock.call_args
        self.assertEqual(kwargs["calibration_report"], report)


class TestSigningKeyBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.default_key = self.tmp / "signing.pem"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generates_a_key_on_first_use_and_reuses_it_after(self):
        with patch.object(run_command, "DEFAULT_SIGNING_KEY", self.default_key), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACCESSBENCH_SIGNING_KEY", None)
            self.assertFalse(self.default_key.exists())
            first = run_command.ensure_signing_key(None)
            self.assertTrue(self.default_key.exists())
            second = run_command.ensure_signing_key(None)
        self.assertEqual(first, second)

    def test_explicit_key_overrides_the_default(self):
        explicit = str(self.tmp / "elsewhere.pem")
        with patch.dict(os.environ, {}, clear=False):
            result = run_command.ensure_signing_key(explicit)
            self.assertEqual(os.environ["ACCESSBENCH_SIGNING_KEY"], explicit)
        self.assertEqual(result, explicit)


class TestSigningKeyTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from accessbench_env.evidence import generate_signing_key
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.registry_path = self.tmp / "TRUSTED_KEYS.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_untrusted_key_does_not_raise_and_names_the_missing_purposes(self):
        with redirect_stdout(StringIO()) as out:
            key_id = run_command.check_signing_key_trust(
                str(self.key), registry_path=self.registry_path
            )
        self.assertEqual(len(key_id), 64)
        self.assertIn("not in the trusted-key registry", out.getvalue())
        self.assertIn("trust add-key", out.getvalue())

    def test_never_mutates_the_registry_itself(self):
        run_command.check_signing_key_trust(str(self.key), registry_path=self.registry_path)
        self.assertFalse(
            self.registry_path.exists(),
            "checking trust must not create or modify TRUSTED_KEYS.json",
        )

    def test_key_admitted_for_all_required_purposes_reads_as_trusted(self):
        import datetime as dt
        from accessbench_env import trust_registry
        from accessbench_env.evidence import load_signing_key, public_key_id

        key_id = public_key_id(load_signing_key(str(self.key)).public_key())
        trust_registry.add_key(
            key_id, list(run_command.TRUST_PURPOSES_FOR_FULL_RUN),
            owner="Test", added_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            path=self.registry_path,
        )
        with redirect_stdout(StringIO()) as out:
            run_command.check_signing_key_trust(str(self.key), registry_path=self.registry_path)
        self.assertIn("listed in TRUSTED_KEYS.json", out.getvalue())
        self.assertIn("not independent validation", out.getvalue())
        self.assertNotIn("independently trusted", out.getvalue())
        self.assertNotIn("not in the trusted-key registry", out.getvalue())

    def test_partial_admission_still_reports_missing(self):
        import datetime as dt
        from accessbench_env import trust_registry
        from accessbench_env.evidence import load_signing_key, public_key_id

        key_id = public_key_id(load_signing_key(str(self.key)).public_key())
        trust_registry.add_key(
            key_id, ["accessbench-anti-cheat-assessment-v1"],
            owner="Test", added_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            path=self.registry_path,
        )
        with redirect_stdout(StringIO()) as out:
            run_command.check_signing_key_trust(str(self.key), registry_path=self.registry_path)
        self.assertIn("accessbench-pre-run-v1", out.getvalue())
        self.assertIn("accessbench-result-v1", out.getvalue())


class TestConformanceGate(unittest.TestCase):
    def test_built_in_enforcement_name_skips_the_probe(self):
        run_command.check_conformance("label_governance")  # must not raise

    def test_failed_conformance_blocks_before_any_spend(self):
        with patch.object(
            run_command, "check_conformance", wraps=run_command.check_conformance
        ):
            with patch(
                "accessbench_env.conformance.run_conformance",
                return_value={"ok": False, "failures": ["endpoint_shape"]},
            ):
                with self.assertRaises(SystemExit):
                    run_command.check_conformance("https://pdp.example.com")


class TestRunEvalArm(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from accessbench_env.evidence import generate_signing_key
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.results_raw = LAB_ROOT / "results_raw"
        self.before = set(p.name for p in self.results_raw.glob("*")) if self.results_raw.exists() else set()
        self.preexisting = set(self.before)

    def tearDown(self):
        if self.results_raw.exists():
            for p in self.results_raw.glob("*"):
                if p.name in self.preexisting:
                    continue
                if "run-command-test" in p.name:
                    p.unlink()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self):
        return {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }

    def test_defaults_to_smoke_mode(self):
        with patch.dict(os.environ, self._env(), clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run):
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            raw_path = run_command.run_eval_arm(
                "run-command-test-model", "label_governance", full=False
            )
        self.assertTrue(raw_path.name.endswith("-smoke.jsonl"))
        self.before.add(raw_path.name)
        self.before.add(raw_path.name + ".manifest.json")

    def test_full_clears_any_inherited_smoke_env_var(self):
        seen = {}

        def _capture_and_exit(*a, **k):
            seen["smoke"] = os.environ.get("ACCESSBENCH_SMOKE_TRIALS")
            raise SystemExit("stop before a real 600-case run")

        env = self._env()
        env["ACCESSBENCH_SMOKE_TRIALS"] = "3"  # simulate an inherited shell var
        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "main", _capture_and_exit):
            with self.assertRaises(SystemExit):
                run_command.run_eval_arm("run-command-test-full", "label_governance", full=True)
        self.assertIsNone(seen.get("smoke"))


class TestFullPipelineThroughAggregate(unittest.TestCase):
    """run_eval_arm feeding aggregate_raw: the exact sequence command_run does.

    A provider that returns a globally-unique response ID per call (as the
    dummy agent does here, and as run_eval_arm alone does not exercise) is
    required for aggregate to accept the manifest -- see the real Ollama
    failure this test suite caught: non-unique response IDs make aggregation
    refuse the run. This test is the regression guard for that path.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from accessbench_env.evidence import generate_signing_key
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.results_raw = LAB_ROOT / "results_raw"
        self.results_root = run_command.RESULTS_ROOT
        self.before_raw = set(p.name for p in self.results_raw.glob("*")) if self.results_raw.exists() else set()
        self.before_results = set(p.name for p in self.results_root.glob("*")) if self.results_root.exists() else set()

    def tearDown(self):
        if self.results_raw.exists():
            for p in self.results_raw.glob("*"):
                if p.name not in self.before_raw and "run-command-aggregate-test" in p.name:
                    p.unlink()
        if self.results_root.exists():
            for p in self.results_root.glob("*"):
                if p.name not in self.before_results and "run-command-aggregate-test" in p.name:
                    shutil.rmtree(p, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_then_aggregate_writes_a_dashboard_ready_summary(self):
        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run):
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            raw_path = run_command.run_eval_arm(
                "run-command-aggregate-test", "label_governance", full=False
            )
            results_root = run_command.aggregate_raw(raw_path)

        self.assertEqual(results_root, self.results_root)
        new_dirs = [
            p for p in self.results_root.glob("*run-command-aggregate-test*")
            if p.name not in self.before_results
        ]
        self.assertEqual(len(new_dirs), 1)
        summary_path = new_dirs[0] / "summary.json"
        self.assertTrue(summary_path.exists())
        summary = json.loads(summary_path.read_text())
        self.assertEqual(summary["meta"]["model"], "run-command-aggregate-test")
        self.assertEqual(summary["meta"]["evaluation_mode"], "smoke")


class TestIntegrityAudit(unittest.TestCase):
    """run_integrity_audit feeding aggregate_raw, the --full sidecar path."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from accessbench_env.evidence import generate_signing_key
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.results_raw = LAB_ROOT / "results_raw"
        self.results_root = run_command.RESULTS_ROOT
        self.before_raw = set(p.name for p in self.results_raw.glob("*")) if self.results_raw.exists() else set()
        self.before_results = set(p.name for p in self.results_root.glob("*")) if self.results_root.exists() else set()

    def tearDown(self):
        if self.results_raw.exists():
            for p in self.results_raw.glob("*"):
                if p.name not in self.before_raw and "run-command-integrity-test" in p.name:
                    p.unlink()
        if self.results_root.exists():
            for p in self.results_root.glob("*"):
                if p.name not in self.before_results and "run-command-integrity-test" in p.name:
                    shutil.rmtree(p, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _no_findings_complete(self, model):
        return lambda request: {"findings": []}

    def test_full_pipeline_produces_a_bound_signed_sidecar_not_a_missing_one(self):
        """The sidecar now exists, validates, and is honest about what's still
        pending. `network_isolation`, `filesystem_isolation`, and
        `anti_cheat_judge_calibration` have no executor yet (tracked
        separately), so the correct outcome today is Flagged with
        AC_REQUIRED_CHECK_NOT_RUN, not Ineligible (sidecar missing) and not a
        false Valid. This is the regression guard for that honesty: it must
        never silently become Ineligible (a wiring bug) or Valid (an invented
        pass) as the surrounding registry checks are implemented in later
        work.
        """
        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(run_command, "_judge_complete", self._no_findings_complete):
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            os.environ.setdefault("ACCESSBENCH_SMOKE_TRIALS", "3")
            raw_path = run_command.run_eval_arm(
                "run-command-integrity-test", "label_governance", full=False
            )
            _trust_anti_cheat_key(str(self.key))
            sidecar_path = run_command.run_integrity_audit(raw_path, "test-judge-model")
            self.assertTrue(sidecar_path.exists())
            results_root = run_command.aggregate_raw(raw_path)

        sidecar = json.loads(sidecar_path.read_text())
        assessment = sidecar["attestation_payload"]["assessment"]
        self.assertEqual(assessment["protocol_checks"]["anti_cheat_judge_completed"], "pass")
        self.assertEqual(assessment["integrity_status"], "Flagged")
        self.assertIn("AC_REQUIRED_CHECK_NOT_RUN", assessment["reason_codes"])

        new_dirs = [
            p for p in results_root.glob("*run-command-integrity-test*")
            if p.name not in self.before_results
        ]
        self.assertEqual(len(new_dirs), 1)
        summary = json.loads((new_dirs[0] / "summary.json").read_text())
        self.assertEqual(
            summary["meta"]["integrity"]["integrity_status"], "Flagged"
        )
        self.assertNotEqual(
            summary["meta"]["integrity"]["reason_codes"], ["AC_ASSESSMENT_MISSING"]
        )

    def test_registry_file_alone_is_honored_with_no_env_var_set(self):
        """The whole point of PR 4: aggregate.py must read trust from
        TRUSTED_KEYS.json itself, not only from the env-var override this
        test suite otherwise uses for convenience. No
        ACCESSBENCH_TRUSTED_ANTI_CHEAT_KEY_IDS is set here at all.
        """
        import datetime as dt
        from accessbench_env import trust_registry
        from accessbench_env.evidence import load_signing_key, public_key_id

        registry_path = self.tmp / "TRUSTED_KEYS.json"
        key_id = public_key_id(load_signing_key(str(self.key)).public_key())
        trust_registry.add_key(
            key_id, ["accessbench-anti-cheat-assessment-v1"],
            owner="Test", added_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            path=registry_path,
        )

        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(trust_registry, "DEFAULT_REGISTRY_PATH", registry_path), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(run_command, "_judge_complete", self._no_findings_complete):
            os.environ.pop("ACCESSBENCH_TRUSTED_ANTI_CHEAT_KEY_IDS", None)
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            os.environ.setdefault("ACCESSBENCH_SMOKE_TRIALS", "3")
            raw_path = run_command.run_eval_arm(
                "run-command-integrity-test-registry", "label_governance", full=False
            )
            sidecar_path = run_command.run_integrity_audit(raw_path, "test-judge-model")
            results_root = run_command.aggregate_raw(raw_path)

        new_dirs = [
            p for p in results_root.glob("*run-command-integrity-test-registry*")
            if p.name not in self.before_results
        ]
        self.assertEqual(len(new_dirs), 1)
        summary = json.loads((new_dirs[0] / "summary.json").read_text())
        integrity = summary["meta"]["integrity"]
        self.assertNotEqual(integrity["reason_codes"], ["AC_ASSESSMENT_MISSING"])
        self.assertNotIn("AC_ASSESSMENT_INVALID", integrity["reason_codes"])
        self.assertNotIn("AC_ASSESSMENT_CONTRACT_INVALID", integrity["reason_codes"])

    def test_judge_failure_marks_the_check_as_error_not_a_silent_pass(self):
        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }

        def _broken_complete(model):
            def complete(request):
                raise RuntimeError("simulated transport failure")
            return complete

        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(run_command, "_judge_complete", _broken_complete):
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            os.environ.setdefault("ACCESSBENCH_SMOKE_TRIALS", "3")
            raw_path = run_command.run_eval_arm(
                "run-command-integrity-test-err", "label_governance", full=False
            )
            _trust_anti_cheat_key(str(self.key))
            sidecar_path = run_command.run_integrity_audit(raw_path, "test-judge-model")

        sidecar = json.loads(sidecar_path.read_text())
        assessment = sidecar["attestation_payload"]["assessment"]
        self.assertEqual(assessment["protocol_checks"]["anti_cheat_judge_completed"], "error")
        self.assertNotEqual(assessment["integrity_status"], "Valid")

    def test_passed_calibration_flips_the_registry_check_from_not_run_to_pass(self):
        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        }
        calibration_report = {
            "gate": "PASS", "precision": 1.0, "n": 24, "calibrated_at": "test",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(run_command, "_judge_complete", self._no_findings_complete):
            os.environ.pop("ACCESSBENCH_SMOKE_TRIALS", None)
            os.environ.setdefault("ACCESSBENCH_SMOKE_TRIALS", "3")
            raw_path = run_command.run_eval_arm(
                "run-command-integrity-test-cal", "label_governance", full=False
            )
            _trust_anti_cheat_key(str(self.key))
            sidecar_path = run_command.run_integrity_audit(
                raw_path, "test-judge-model", calibration_report=calibration_report
            )

        sidecar = json.loads(sidecar_path.read_text())
        assessment = sidecar["attestation_payload"]["assessment"]
        self.assertEqual(
            assessment["protocol_checks"]["anti_cheat_judge_calibration"], "pass"
        )
        self.assertIn(
            "anti_cheat_judge_calibration", assessment["protocol_check_evidence"]
        )


class TestEnforcementAlias(unittest.TestCase):
    def test_benchmark_alias_resolves_to_the_built_in_id_and_says_so(self):
        out = StringIO()
        with redirect_stdout(out):
            resolved, alias = run_command.resolve_enforcement_arg("benchmark")
        self.assertEqual((resolved, alias), ("benchmark_pdp_v3", "benchmark"))
        self.assertIn(
            "enforcement: benchmark -> benchmark_pdp_v3 (the Benchmark PDP, reference decision point)",
            out.getvalue(),
        )

    def test_other_values_pass_through_unchanged(self):
        for value in ("label_governance", "benchmark_pdp_v3", "https://pdp.example.com/access/v1"):
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(run_command.resolve_enforcement_arg(value), (value, None))
            self.assertEqual(out.getvalue(), "")


class TestResumeFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_raw_is_refused_with_the_path_named(self):
        missing = self.tmp / "nope.jsonl"
        with self.assertRaises(SystemExit) as ctx:
            run_command.prepare_resume(str(missing))
        self.assertIn(str(missing), str(ctx.exception))
        self.assertIn("results_raw", str(ctx.exception))

    def test_raw_without_manifest_is_refused(self):
        raw = self.tmp / "r.jsonl"
        raw.write_text("")
        with self.assertRaises(SystemExit) as ctx:
            run_command.prepare_resume(str(raw))
        self.assertIn("manifest", str(ctx.exception))

    def test_existing_raw_sets_the_runner_env_var(self):
        raw = self.tmp / "r.jsonl"
        raw.write_text("")
        Path(str(raw) + ".manifest.json").write_text("{}")
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(StringIO()):
            os.environ.pop("ACCESSBENCH_RESUME_RAW", None)
            run_command.prepare_resume(str(raw))
            self.assertEqual(os.environ["ACCESSBENCH_RESUME_RAW"], str(raw.resolve()))

    def test_resume_command_is_exact(self):
        cmd = run_command.resume_command("m", "benchmark", True, Path("/x/raw.jsonl"))
        self.assertEqual(cmd, "accessbench run --model m --enforcement benchmark --full --resume /x/raw.jsonl")

    def test_run_failure_after_raw_exists_prints_the_resume_command(self):
        raw = run_command.RESULTS_RAW / "19990101T000000000000Z-run-command-resume-test.jsonl"

        def _explode(model, enforcement, full):
            raw.write_text("")
            raise SystemExit("simulated transport abort")

        out = StringIO()
        try:
            with patch.dict(os.environ, {"ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1"}, clear=False), \
                 patch.object(run_command, "preflight", lambda **k: "key"), \
                 patch.object(run_command, "run_eval_arm", _explode), \
                 redirect_stdout(out):
                args = cli.parser().parse_args(["run", "--model", "m", "--enforcement", "benchmark"])
                with self.assertRaises(SystemExit):
                    cli.command_run(args)
        finally:
            raw.unlink(missing_ok=True)
        self.assertIn(f"accessbench run --model m --enforcement benchmark --resume {raw.resolve()}", out.getvalue())


class TestPreflight(unittest.TestCase):
    def test_order_is_key_credentials_disk_conformance_model(self):
        order = []
        with patch.object(run_command, "ensure_signing_key", lambda e: order.append("signing key") or "k"), \
             patch.object(run_command, "preflight_credentials", lambda: order.append("credentials")), \
             patch.object(run_command, "preflight_disk", lambda: order.append("disk")), \
             patch.object(run_command, "check_conformance", lambda e: order.append("conformance")), \
             patch.object(run_command, "preflight_model_tool_use", lambda m: order.append("model")), \
             redirect_stdout(StringIO()):
            run_command.preflight(enforcement="benchmark_pdp_v3", signing_key=None, model="m")
        self.assertEqual(order, ["signing key", "credentials", "disk", "conformance", "model"])

    def test_skip_model_preflight_skips_only_the_last_step(self):
        called = []
        out = StringIO()
        with patch.object(run_command, "ensure_signing_key", lambda e: "k"), \
             patch.object(run_command, "preflight_credentials", lambda: None), \
             patch.object(run_command, "preflight_disk", lambda: None), \
             patch.object(run_command, "preflight_model_tool_use", lambda m: called.append(m)), \
             redirect_stdout(out):
            run_command.preflight(enforcement="label_governance", signing_key=None, model="m", skip_model_preflight=True)
        self.assertEqual(called, [])
        self.assertIn("preflight: model tool use: skipped", out.getvalue())

    def test_hosted_endpoint_without_credentials_names_each_missing_variable(self):
        env = {"ACCESSBENCH_MODEL_BASE_URL": "https://api.example.com/v1"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("ACCESSBENCH_SPEND_APPROVED", None)
            with self.assertRaises(SystemExit) as ctx:
                run_command.preflight_credentials()
            message = str(ctx.exception)
            self.assertIn("OPENAI_API_KEY", message)
            self.assertIn("ACCESSBENCH_SPEND_APPROVED", message)
            os.environ["OPENAI_API_KEY"] = "sk-test"
            with self.assertRaises(SystemExit) as ctx:
                run_command.preflight_credentials()
            self.assertNotIn("OPENAI_API_KEY is not set", str(ctx.exception))
            self.assertIn("ACCESSBENCH_SPEND_APPROVED", str(ctx.exception))

    def test_local_endpoint_needs_no_credentials(self):
        out = StringIO()
        with patch.dict(os.environ, {"ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1"}, clear=False), \
             redirect_stdout(out):
            os.environ.pop("OPENAI_API_KEY", None)
            run_command.preflight_credentials()
        self.assertIn("preflight: credentials: ok", out.getvalue())

    def test_disk_check_reports_free_space_and_fails_when_short(self):
        out = StringIO()
        with redirect_stdout(out):
            run_command.preflight_disk(min_free_bytes=1)
        self.assertIn("preflight: disk: ok", out.getvalue())
        self.assertIn("GB free", out.getvalue())
        fake = type("U", (), {"free": 1024, "total": 10, "used": 5})()
        with patch.object(run_command.shutil, "disk_usage", lambda p: fake):
            with self.assertRaises(SystemExit) as ctx:
                run_command.preflight_disk()
        self.assertIn("GB free", str(ctx.exception))

    def test_model_tool_use_rejects_prose_and_accepts_a_tool_call(self):
        class _Fn:
            name = "record_check"

        class _Call:
            function = _Fn()

        class _Msg:
            def __init__(self, calls):
                self.tool_calls = calls

        class _Resp:
            def __init__(self, calls):
                self.choices = [type("C", (), {"message": _Msg(calls)})()]

        class _Client:
            def __init__(self, calls, **kwargs):
                self.calls = calls
                self.chat = type("Chat", (), {})()
                self.chat.completions = type("Comp", (), {})()
                self.chat.completions.create = lambda **req: _Resp(self.calls)

        import openai
        with patch.dict(os.environ, {"ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1"}, clear=False):
            with patch.object(openai, "OpenAI", lambda **kw: _Client([])):
                with self.assertRaises(SystemExit) as ctx:
                    run_command.preflight_model_tool_use("m")
                self.assertIn("without a structured tool call", str(ctx.exception))
            out = StringIO()
            with patch.object(openai, "OpenAI", lambda **kw: _Client([_Call()])), redirect_stdout(out):
                run_command.preflight_model_tool_use("m")
            self.assertIn("preflight: model tool use: ok", out.getvalue())


class TestSpendEstimate(unittest.TestCase):
    def test_local_endpoint_prints_nothing(self):
        out = StringIO()
        with patch.dict(os.environ, {"ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1"}, clear=False), \
             redirect_stdout(out):
            run_command.print_spend_estimate(full=True)
        self.assertEqual(out.getvalue(), "")

    def test_hosted_endpoint_prints_three_lines_and_scales_smoke(self):
        env = {"ACCESSBENCH_MODEL_BASE_URL": "https://api.example.com/v1", "ACCESSBENCH_SMOKE_TRIALS": "6"}
        out = StringIO()
        with patch.dict(os.environ, env, clear=False), redirect_stdout(out):
            os.environ.pop("ACCESSBENCH_PRICE_PER_M_INPUT", None)
            os.environ.pop("ACCESSBENCH_PRICE_PER_M_OUTPUT", None)
            run_command.print_spend_estimate(full=False)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("smoke: 6 cases x 2 arms = 12 episodes", lines[0])
        self.assertIn("2.7M prompt and 0.13M completion tokens per 1,200 episodes", lines[1])
        self.assertIn("AccessBench does not know your rate", lines[2])
        out = StringIO()
        env.update({"ACCESSBENCH_PRICE_PER_M_INPUT": "2.50", "ACCESSBENCH_PRICE_PER_M_OUTPUT": "10"})
        with patch.dict(os.environ, env, clear=False), redirect_stdout(out):
            run_command.print_spend_estimate(full=True)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("1,200 episodes", lines[0])
        self.assertIn("USD 8.05", lines[2])  # 2.7 * 2.50 + 0.13 * 10


class TestDemoDefaults(unittest.TestCase):
    def test_demo_needs_no_arguments_and_says_it_is_not_a_result(self):
        args = cli.parser().parse_args(["demo"])
        self.assertEqual(Path(args.catalog), run_command.CORE_CATALOG)
        self.assertEqual(args.limit, 6)
        out = StringIO()
        with redirect_stdout(out):
            cli.command_demo(args)
        text = out.getvalue()
        self.assertIn("zero-cost grader proof, not a benchmark result", text)
        self.assertEqual(len(json.loads(text[: text.rindex("]") + 1])), 6)


class TestBundleAssembly(unittest.TestCase):
    """`accessbench run --model M --enforcement benchmark`, end to end and offline."""

    MODEL = "run-command-bundle-test"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from accessbench_env.evidence import generate_signing_key
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.results_raw = LAB_ROOT / "results_raw"
        self.results_root = run_command.RESULTS_ROOT
        self.before_raw = set(p.name for p in self.results_raw.glob("*")) if self.results_raw.exists() else set()
        self.before_results = set(p.name for p in self.results_root.glob("*")) if self.results_root.exists() else set()

    def tearDown(self):
        for p in self.results_raw.glob("*"):
            if p.name not in self.before_raw and self.MODEL in p.name:
                p.unlink()
        for p in self.results_root.glob("*"):
            if p.name not in self.before_results and self.MODEL in p.name:
                shutil.rmtree(p, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_writes_a_self_contained_bundle(self):
        import hashlib
        env = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
            "ACCESSBENCH_SMOKE_TRIALS": "3",
        }
        out = StringIO()
        with patch.dict(os.environ, env, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(run_command, "preflight_model_tool_use", lambda model: None), \
             redirect_stdout(out):
            args = cli.parser().parse_args(["run", "--model", self.MODEL, "--enforcement", "benchmark"])
            cli.command_run(args)
        text = out.getvalue()
        for line in (
            "enforcement: benchmark -> benchmark_pdp_v3",
            "preflight: signing key: ok",
            "preflight: credentials: ok",
            "preflight: disk: ok",
            "preflight: pdp conformance: ok",
            "SMOKE SAMPLE, NOT A REPORTABLE RESULT",
            "verify it: accessbench verify ",
        ):
            self.assertIn(line, text)
        new_dirs = [p for p in self.results_root.glob(f"*{self.MODEL}*") if p.name not in self.before_results]
        self.assertEqual(len(new_dirs), 1)
        bundle = new_dirs[0]
        evidence = bundle / "evidence"
        raws = list(evidence.glob("*.jsonl"))
        self.assertEqual(len(raws), 1)
        self.assertTrue((evidence / (raws[0].name + ".manifest.json")).exists())
        for name in ("summary.json", "run.json", "report.html", "VERIFY.txt"):
            self.assertTrue((bundle / name).exists(), name)

        run_json = json.loads((bundle / "run.json").read_text())
        self.assertEqual(run_json["enforcement"]["resolved_id"], "benchmark_pdp_v3")
        self.assertEqual(run_json["enforcement"]["alias_used"], "benchmark")
        self.assertEqual(run_json["config"]["benchmark_inputs"]["enforcement"], "benchmark_pdp_v3")
        self.assertEqual(run_json["config"]["evaluation_mode"], "smoke")
        self.assertIn("platform", run_json["host"])
        for name, digest in run_json["evidence_sha256"].items():
            self.assertEqual(hashlib.sha256((evidence / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(
            hashlib.sha256((bundle / "summary.json").read_bytes()).hexdigest(), run_json["summary_sha256"]
        )

        verify_txt = (bundle / "VERIFY.txt").read_text()
        self.assertIn(f"accessbench verify {bundle.resolve()}", verify_txt)
        self.assertIn(run_json["summary_sha256"], verify_txt)
        self.assertIn(run_json["evidence_sha256"][raws[0].name], verify_txt)

        html = (bundle / "report.html").read_text()
        self.assertIn("SMOKE SAMPLE, NOT A REPORTABLE RESULT (3 cases)", html)
        self.assertIn("behind the Benchmark PDP, the reference decision point", html)
        self.assertIn("foundation model behavior, no enforcement", html)
        self.assertIn("Development-bank measurement; not a publishable model claim", html)
        self.assertIn("<svg", html)
        self.assertIn("#c9364f", html)
        self.assertIn("#8a8a93", html)
        self.assertIn(f"accessbench verify {bundle.resolve()}", html)
        self.assertNotIn("\u2014", html)
        # summary.json is untouched by bundling: the dashboard still reads it as before
        summary = json.loads((bundle / "summary.json").read_text())
        self.assertEqual(summary["meta"]["model"], self.MODEL)


if __name__ == "__main__":
    unittest.main()
