# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for `accessbench verify`, the one-command bundle verifier.

A real bundle is built once, offline, by driving `accessbench run` with the
subject agent replaced by the deterministic reference path (the same stub the
runner tests use). The verifier is then run against that bundle intact, with
a tampered raw, with a tampered summary, and in the legacy --raw layout.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(LAB_ROOT / "eval"))

import run_eval  # noqa: E402
from accessbench_env import cli, run_command, verify_result  # noqa: E402
from accessbench_env.evidence import generate_signing_key  # noqa: E402
from accessbench_env.sandbox import Sandbox  # noqa: E402

MODEL = "verify-result-test-model"


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
            "request_parallel_tool_calls": k.get("parallel_tool_calls", False),
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


def build_bundle_offline(model: str, key_path: Path) -> tuple[Path, str]:
    """Drive `accessbench run --model M --enforcement benchmark` fully offline."""
    env = {
        "ACCESSBENCH_SIGNING_KEY": str(key_path),
        "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
        "ACCESSBENCH_SMOKE_TRIALS": "4",
    }
    out = StringIO()
    with patch.dict(os.environ, env, clear=False), \
         patch.object(run_eval, "SubjectAgent", _DummyAgent), \
         patch.object(run_eval, "run_agent_trial", _reference_run), \
         patch.object(run_command, "preflight_model_tool_use", lambda model: None), \
         redirect_stdout(out):
        args = cli.parser().parse_args(["run", "--model", model, "--enforcement", "benchmark"])
        cli.command_run(args)
    text = out.getvalue()
    marker = "result bundle: "
    line = next(l for l in text.splitlines() if l.startswith(marker))
    return Path(line[len(marker):].strip()), text


class _CleanupMixin:
    @classmethod
    def _snapshot(cls):
        cls.results_raw = LAB_ROOT / "results_raw"
        cls.results_root = run_command.RESULTS_ROOT
        cls.before_raw = {p.name for p in cls.results_raw.glob("*")} if cls.results_raw.exists() else set()
        cls.before_results = {p.name for p in cls.results_root.glob("*")} if cls.results_root.exists() else set()

    @classmethod
    def _cleanup(cls, token: str):
        if cls.results_raw.exists():
            for p in cls.results_raw.glob("*"):
                if p.name not in cls.before_raw and token in p.name:
                    p.unlink()
        if cls.results_root.exists():
            for p in cls.results_root.glob("*"):
                if p.name not in cls.before_results and token in p.name:
                    shutil.rmtree(p, ignore_errors=True)


class TestVerifyBuiltBundle(_CleanupMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.key = cls.tmp / "signing.pem"
        generate_signing_key(cls.key)
        cls._snapshot()
        cls.bundle, cls.run_output = build_bundle_offline(MODEL, cls.key)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup(MODEL)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _copy_bundle(self) -> Path:
        target = self.tmp / f"copy-{os.urandom(3).hex()}"
        shutil.copytree(self.bundle, target)
        return target

    def test_intact_bundle_passes_every_check(self):
        result = verify_result.verify_result(self.bundle)
        statuses = {c["check"]: c["status"] for c in result["checks"]}
        self.assertTrue(result["ok"], result)
        for check in ("bundle shape", "raw sha256", "completeness", "hash chain", "signatures", "recompute"):
            self.assertEqual(statuses[check], "PASS", result)
        self.assertEqual(statuses["signing key"], "INFO")
        self.assertEqual(statuses["integrity sidecar"], "INFO")
        text = verify_result.format_report(result)
        self.assertIn("foundation model behavior, no enforcement", text)
        self.assertIn("behind the Benchmark PDP, the reference decision point", text)
        self.assertIn("SMOKE SAMPLE, NOT A REPORTABLE RESULT", text)
        self.assertIn("result: VERIFIED", text)
        self.assertIn("self-signed by the operator's key", text)

    def test_verify_subcommand_exits_zero_and_json_flag_is_machine_readable(self):
        out = StringIO()
        with redirect_stdout(out):
            cli.command_verify(cli.parser().parse_args(["verify", str(self.bundle), "--json"]))
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["numbers"]["evaluation_mode"], "smoke")

    def test_tampered_raw_fails_digest_and_chain(self):
        copy = self._copy_bundle()
        raw = next(p for p in (copy / "evidence").glob("*.jsonl"))
        lines = raw.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["verbatim_violation"] = not record.get("verbatim_violation")
        lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        raw.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_result.verify_result(copy)
        statuses = {c["check"]: c["status"] for c in result["checks"]}
        self.assertFalse(result["ok"])
        self.assertEqual(statuses["raw sha256"], "FAIL")
        self.assertEqual(statuses["hash chain"], "FAIL")
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            cli.command_verify(cli.parser().parse_args(["verify", str(copy)]))
        self.assertIn("result: FAILED", out.getvalue())

    def test_tampered_summary_fails_recompute_only(self):
        copy = self._copy_bundle()
        summary_path = copy / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        block = summary["summary"]["none"]["governed_task_pass"]
        block["positive_n"] = block["positive_n"] + 1
        summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        result = verify_result.verify_result(copy)
        statuses = {c["check"]: c["status"] for c in result["checks"]}
        self.assertFalse(result["ok"])
        self.assertEqual(statuses["recompute"], "FAIL")
        self.assertIn("none.governed_task_pass", next(c["reason"] for c in result["checks"] if c["check"] == "recompute"))
        for check in ("raw sha256", "hash chain", "signatures", "completeness"):
            self.assertEqual(statuses[check], "PASS")

    def test_legacy_layout_verifies_through_raw_flag(self):
        copy = self._copy_bundle()
        raw_src = next(p for p in (copy / "evidence").glob("*.jsonl"))
        legacy_raw_dir = self.tmp / "legacy_raw"
        legacy_raw_dir.mkdir(exist_ok=True)
        for p in (copy / "evidence").iterdir():
            shutil.copy2(p, legacy_raw_dir / p.name)
        shutil.rmtree(copy / "evidence")
        for extra in ("run.json", "report.html", "VERIFY.txt"):
            (copy / extra).unlink(missing_ok=True)
        without_raw = verify_result.verify_result(copy)
        self.assertFalse(without_raw["ok"])
        self.assertIn("--raw", without_raw["checks"][0]["reason"])
        with_raw = verify_result.verify_result(copy, raw=legacy_raw_dir / raw_src.name)
        self.assertTrue(with_raw["ok"], with_raw)
        self.assertIn("legacy layout", with_raw["checks"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
