# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""End-to-end runner tests: development smoke mode and resume after interruption.

The subject agent is replaced by the deterministic reference path so no model
call happens. Everything else (manifest, attestation, chain, aggregate-ready
records) is the real runner.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(LAB_ROOT / "eval"))

import run_eval  # noqa: E402
from accessbench_env.agent_runner import is_transport_failure  # noqa: E402
from accessbench_env.evidence import generate_signing_key, verify_record_chain  # noqa: E402
from accessbench_env.sandbox import Sandbox  # noqa: E402


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


class TestSmokeAndResume(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key = self.tmp / "signing.pem"
        generate_signing_key(self.key)
        self.results_raw = LAB_ROOT / "results_raw"
        self.before = set(p.name for p in self.results_raw.glob("*")) if self.results_raw.exists() else set()
        # preexisting never changes; before is the working filter tests adjust
        self.preexisting = set(self.before)

    def tearDown(self):
        # Remove everything this test created under results_raw. Test fixtures
        # must never accumulate beside real evidence.
        if self.results_raw.exists():
            for p in self.results_raw.glob("*"):
                if p.name in self.preexisting:
                    continue
                if "smoke-test-model" in p.name or "broke-model" in p.name:
                    p.unlink()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, env, extra_argv=()):
        base = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
            "ACCESSBENCH_SMOKE_TRIALS": "2",
        }
        base.update(env)
        with patch.dict(os.environ, base, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", _reference_run), \
             patch.object(
                 run_eval, "_git_state",
                 return_value={"commit": "test-commit", "dirty": False, "source": "test"},
             ), \
             patch.object(run_eval, "EPISODE_BACKOFF_S", (0.0, 0.0)), \
             patch.object(
                 sys, "argv",
                 ["run_eval.py", "--model", "smoke-test-model",
                  "--enforcement", "label_governance", *extra_argv],
             ):
            run_eval.main()
        new = sorted(
            p for p in self.results_raw.glob("*-smoke.jsonl") if p.name not in self.before
        )
        return new

    def test_smoke_mode_runs_a_handful_and_is_never_eligible(self):
        raws = self._run({
            "ACCESSBENCH_MODEL_WEIGHT_REVISION": "weight-sha",
            "ACCESSBENCH_MODEL_QUANTIZATION": "test-quant",
            "ACCESSBENCH_MODEL_SERVER_SOFTWARE": "vllm",
            "ACCESSBENCH_MODEL_SERVER_VERSION": "test-version",
            "ACCESSBENCH_MODEL_SERVER_CONFIG_SHA256": "a" * 64,
            "ACCESSBENCH_MODEL_PREFLIGHT_SHA256": "b" * 64,
            "ACCESSBENCH_MODEL_ORCHESTRATOR_SHA256": "c" * 64,
        })
        self.assertEqual(len(raws), 1)
        raw = raws[0]
        records = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
        self.assertEqual(len(records), 2 * 2 * 1)  # 2 trials, 2 arms, 1 protocol pass
        verify_record_chain(records)
        manifest = json.loads(Path(str(raw) + ".manifest.json").read_text())
        self.assertEqual(manifest["schema_version"], "accessbench-live-run-v4")
        self.assertEqual(manifest["config"]["k_repeats"], 1)
        self.assertEqual(manifest["config"]["evaluation_mode"], "smoke")
        self.assertFalse(manifest["config"]["bank_complete"])
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["unresolved_episode_n"], 0)
        self.assertEqual(manifest["unexpected_episode_n"], 0)
        self.assertEqual(manifest["exhausted_episode_attempt_n"], 0)
        self.assertFalse(manifest["transport"]["abort"]["tripped"])
        self.assertIn("transport", manifest)
        self.assertEqual(
            manifest["config"]["model_weight_revision"], "weight-sha"
        )
        self.assertEqual(manifest["config"]["model_server"]["software"], "vllm")
        self.assertEqual(
            manifest["observed_enforcement_identities"],
            [
                {"id": "accessbench-label-governance", "version": "1", "state_scope": "episode"},
                {"id": "accessbench-none", "version": "1", "state_scope": "none"},
            ],
        )
        self.before.add(raw.name); self.before.add(raw.name + ".manifest.json")
        # not eligible: aggregate treats non-core as diagnostic
        from aggregate import _release_mode_ineligibility_reasons
        self.assertIn(
            "diagnostic_sample_not_release_eligible",
            _release_mode_ineligibility_reasons(manifest),
        )
        from aggregate import _validate_manifest
        validation = _validate_manifest(
            manifest,
            raw,
            str(LAB_ROOT / "catalog" / "core_v2.jsonl"),
            records,
        )
        self.assertTrue(validation["complete"])


    def test_persistent_transport_failure_aborts_without_writing_records(self):
        """A credit stop must abort the run, not fill it with scored garbage.

        Episodes that never reached the model are not written at all, so the
        raw stays clean and a later resume re-runs exactly those episodes.
        """
        class _RateLimit(Exception):
            pass
        _RateLimit.__name__ = "RateLimitError"

        def always_broke(trial, enforcer=None, agent=None, completion_fn=None):
            raise _RateLimit("Error code: 429 - You have no credits remaining.")

        base = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
            "ACCESSBENCH_SMOKE_TRIALS": "5",
        }
        output = io.StringIO()
        with patch.dict(os.environ, base, clear=False), \
             patch.object(run_eval, "SubjectAgent", _DummyAgent), \
             patch.object(run_eval, "run_agent_trial", always_broke), \
             patch.object(run_eval, "EPISODE_BACKOFF_S", (0.0, 0.0)), \
             patch.object(run_eval, "TRANSPORT_ABORT_STREAK", 3), \
             patch.object(sys, "argv", ["run_eval.py", "--model", "broke-model", "--enforcement", "label_governance"]), \
             redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                run_eval.main()
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("INCOMPLETE", output.getvalue())
        self.assertRegex(output.getvalue(), r"(?m)^RAW_PATH=.+\.jsonl$")
        # Nothing reached the model, so no episode was written at all: the raw
        # file is absent or empty and the manifest is not complete.
        manifests = sorted(self.results_raw.glob("*broke-model-smoke.jsonl.manifest.json"))
        self.assertEqual(len(manifests), 1)
        raw = Path(str(manifests[0]).replace(".manifest.json", ""))
        self.assertFalse(raw.exists() and raw.read_text().strip())
        manifest = json.loads(manifests[0].read_text())
        self.assertEqual(manifest.get("status"), "incomplete")
        self.assertGreater(manifest["unresolved_episode_n"], 0)
        self.assertGreater(manifest["exhausted_episode_attempt_n"], 0)
        self.assertTrue(manifest["transport"]["abort"]["tripped"])
        self.assertIn("result_attestation", manifest)
        for failure in manifest["transport"]["exhausted_episode_attempts"]:
            self.assertEqual(failure["exception_type"], "RateLimitError")
            self.assertNotIn("error", failure)
            self.assertEqual(len(failure["message_sha256"]), 64)
        manifests[0].unlink()
        if raw.exists():
            raw.unlink()


    def test_resume_continues_the_chain_without_double_counting(self):
        raws = self._run({}, extra_argv=("--repeats", "3"))
        raw = raws[0]
        lines = raw.read_text().splitlines()
        self.assertEqual(len(lines), 12)
        # simulate an interruption after 5 episodes
        raw.write_text("\n".join(lines[:5]) + "\n")
        manifest_path = Path(str(raw) + ".manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["status"] = "running"
        manifest_path.write_text(json.dumps(manifest))
        self.before.discard(raw.name)
        resumed = self._run(
            {"ACCESSBENCH_RESUME_RAW": str(raw)}, extra_argv=("--repeats", "3")
        )
        self.assertEqual([p.name for p in resumed], [raw.name])
        records = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
        self.assertEqual(len(records), 12)
        verify_record_chain(records)
        keys = [(r["enforcer"], r["trial_id"], r["repeat"]) for r in records]
        self.assertEqual(len(keys), len(set(keys)))
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(len(manifest["resumed_at"]), 1)


    def test_resume_from_an_empty_raw_restarts_cleanly(self):
        """A raw file with zero lines plus a valid manifest resumes from nothing."""
        raws = self._run({}, extra_argv=("--repeats", "3"))
        raw = raws[0]
        raw.write_text("")
        manifest_path = Path(str(raw) + ".manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["status"] = "running"
        manifest_path.write_text(json.dumps(manifest))
        self.before.discard(raw.name)
        resumed = self._run(
            {"ACCESSBENCH_RESUME_RAW": str(raw)}, extra_argv=("--repeats", "3")
        )
        self.assertEqual([p.name for p in resumed], [raw.name])
        records = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
        self.assertEqual(len(records), 12)
        verify_record_chain(records)
        self.assertEqual(records[0]["chain_index"], 0)
        self.assertIsNone(records[0]["previous_record_sha256"])


    def test_hosted_endpoint_refuses_to_run_without_explicit_spend_approval(self):
        """Money is never spent by default. A hosted base URL needs approval."""
        base = {
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_MODEL_BASE_URL": "https://api.openai.com/v1",
            "ACCESSBENCH_SMOKE_TRIALS": "1",
        }
        base.pop("ACCESSBENCH_SPEND_APPROVED", None)
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with patch.dict(os.environ, base, clear=False), \
             patch.object(sys, "argv", ["run_eval.py", "--model", "m", "--enforcement", "label_governance"]), \
             redirect_stderr(err):
            os.environ.pop("ACCESSBENCH_SPEND_APPROVED", None)
            with self.assertRaises(SystemExit) as caught:
                run_eval.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("spend", err.getvalue().lower())
        # local endpoints are exempt: the existing smoke tests run against localhost

    def test_resume_refuses_a_different_configuration(self):
        raws = self._run({})
        raw = raws[0]
        with self.assertRaises(SystemExit):
            self._run({"ACCESSBENCH_RESUME_RAW": str(raw), "ACCESSBENCH_SMOKE_TRIALS": "3"})

    def test_resume_refuses_a_manifest_from_another_schema_version(self):
        raws = self._run({})
        raw = raws[0]
        manifest_path = Path(str(raw) + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = "accessbench-live-run-v3"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self._run({"ACCESSBENCH_RESUME_RAW": str(raw)})
        self.assertIn("schema", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
