# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Independent acceptance tests for run evidence, resume, and pod controls."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
TEST_BASH = os.environ.get("ACCESSBENCH_TEST_BASH", "bash")


def _bash_major_version(bash: str) -> int:
    """Major version of the bash the pod-control tests will run, 0 if unusable."""
    try:
        probe = subprocess.run(
            [bash, "-c", 'echo "${BASH_VERSINFO[0]}"'],
            capture_output=True, text=True, check=False, timeout=10,
        )
        return int(probe.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


BASH_MAJOR = _bash_major_version(TEST_BASH)
BASH_TOO_OLD = (
    f"tools/runpod/*.sh need Bash 4 or newer; {TEST_BASH} is {BASH_MAJOR}.x "
    "(stock macOS bash is 3.2). Install a newer bash and point "
    "ACCESSBENCH_TEST_BASH at it to run these two tests; CI runs them on Linux."
)
sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(LAB_ROOT / "eval"))

import aggregate  # noqa: E402
import run_eval  # noqa: E402
from accessbench_env.evidence import (  # noqa: E402
    CHAIN_FIELDS,
    chain_record,
    generate_signing_key,
    load_signing_key,
    sign_attestation,
    verify_attestation,
    verify_record_chain,
)
from accessbench_env.sandbox import Sandbox  # noqa: E402


class _DummyAgent:
    def __init__(self, *args, **kwargs):
        self.client_episode_session_id = os.urandom(12).hex()
        self.response_metadata = [{
            "api_mode": "chat_completions",
            "id": f"response-{os.urandom(8).hex()}",
            "model": kwargs["model"],
            "request_temperature": 0.0,
            "request_temperature_sent": True,
            "request_seed": kwargs.get("seed"),
            "request_seed_sent": True,
            "request_enable_thinking": False,
            "request_enable_thinking_sent": False,
            "reasoning_effort": None,
            "request_reasoning_sent": False,
            "request_parallel_tool_calls": kwargs.get(
                "parallel_tool_calls", False
            ),
            "request_parallel_tool_calls_sent": True,
            "client_episode_session_id": self.client_episode_session_id,
        }]


def _reference_run(trial, enforcer=None, agent=None, completion_fn=None):
    run = Sandbox(trial, enforcer).run_reference()
    run.update({
        "delivered": run["final_status"] == "completed",
        "delivery_attempted": True,
        "blocked_delivery": run["blocked_calls"] > 0,
        "subject_trace": [],
        "model_responses": list(agent.response_metadata),
    })
    return run


class _RunHarness(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.signing_key_path = self.temp / "signing.pem"
        generate_signing_key(self.signing_key_path)
        self.before = {
            path.name for path in (LAB_ROOT / "results_raw").glob("*")
        }

    def tearDown(self):
        results_raw = LAB_ROOT / "results_raw"
        for path in results_raw.glob("*"):
            if path.name not in self.before and "acceptance-" in path.name:
                path.unlink()
        shutil.rmtree(self.temp, ignore_errors=True)

    def _invoke(
        self,
        model: str,
        runner,
        *,
        resume_raw: Path | None = None,
        abort_streak: int = 10,
    ):
        environment = {
            "ACCESSBENCH_SIGNING_KEY": str(self.signing_key_path),
            "ACCESSBENCH_MODEL_BASE_URL": "http://localhost:1/v1",
            "ACCESSBENCH_SMOKE_TRIALS": "2",
        }
        if resume_raw is not None:
            environment["ACCESSBENCH_RESUME_RAW"] = str(resume_raw)
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch.object(
            run_eval, "SubjectAgent", _DummyAgent
        ), patch.object(
            run_eval, "run_agent_trial", runner
        ), patch.object(
            run_eval,
            "_git_state",
            return_value={"commit": "acceptance-commit", "dirty": False, "source": "test"},
        ), patch.object(
            run_eval, "EPISODE_BACKOFF_S", (0.0, 0.0)
        ), patch.object(
            run_eval, "TRANSPORT_ABORT_STREAK", abort_streak
        ), patch.object(
            sys,
            "argv",
            [
                "run_eval.py",
                "--model",
                model,
                "--enforcement",
                "benchmark_pdp_v3",
            ],
        ), redirect_stdout(output):
            error = None
            try:
                run_eval.main()
            except SystemExit as exc:
                error = exc
        match = re.search(r"(?m)^RAW_PATH=(.+)$", output.getvalue())
        self.assertIsNotNone(match, output.getvalue())
        return error, output.getvalue(), Path(match.group(1))


class TestFailureEvidenceAndResume(_RunHarness):
    def test_exhaustion_is_secret_safe_signed_incomplete_and_resumable(self):
        class SecretRateLimit(Exception):
            pass

        SecretRateLimit.__name__ = "RateLimitError"

        def fail(*args, **kwargs):
            error = SecretRateLimit(
                "OPENAI_API_KEY=sk-super-secret billing authorization failed"
            )
            error.status_code = "sk-secret-status"
            error.code = "sk-secret-provider-code"
            raise error

        error, output, raw_path = self._invoke(
            "acceptance-transport-model", fail, abort_streak=1
        )
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 3)
        self.assertIn("INCOMPLETE", output)
        self.assertNotRegex(output, r"(?m)^DONE")
        self.assertNotIn("sk-super-secret", output)
        self.assertNotIn("sk-secret-status", output)
        self.assertNotIn("sk-secret-provider-code", output)

        manifest_path = Path(str(raw_path) + ".manifest.json")
        manifest_text = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("sk-super-secret", manifest_text)
        self.assertNotIn("sk-secret-status", manifest_text)
        self.assertNotIn("sk-secret-provider-code", manifest_text)
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["status"], "incomplete")
        self.assertGreater(manifest["unresolved_episode_n"], 0)
        self.assertGreater(manifest["exhausted_episode_attempt_n"], 0)
        self.assertTrue(manifest["transport"]["abort"]["tripped"])
        for failure in manifest["transport"]["exhausted_episode_attempts"]:
            self.assertEqual(failure["exception_type"], "RateLimitError")
            self.assertLessEqual(
                set(failure),
                {
                    "recorded_at", "enforcer", "reference_id", "repeat",
                    "attempt_n", "exception_type", "status_code",
                    "provider_code_sha256", "message_sha256",
                },
            )
            self.assertRegex(failure["message_sha256"], r"^[0-9a-f]{64}$")
        verify_attestation(
            manifest["result_attestation_payload"],
            manifest["result_attestation"],
            purpose="accessbench-result-v1",
        )

        resumed_error, resumed_output, resumed_path = self._invoke(
            "acceptance-transport-model",
            _reference_run,
            resume_raw=raw_path,
        )
        self.assertIsNone(resumed_error)
        self.assertEqual(resumed_path, raw_path)
        self.assertRegex(resumed_output, r"(?m)^DONE")
        records = [
            json.loads(line)
            for line in raw_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verify_record_chain(records)
        keys = [run_eval._episode_key(record) for record in records]
        self.assertEqual(len(keys), len(set(keys)))
        resumed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(resumed_manifest["status"], "complete")
        self.assertEqual(resumed_manifest["unresolved_episode_n"], 0)
        self.assertFalse(resumed_manifest["transport"]["abort"]["tripped"])


class TestPublicAndSealedResumeIdentity(unittest.TestCase):
    def test_public_and_opaque_keys_match_their_scheduled_episode(self):
        public_record = {
            "enforcer": "none",
            "trial_id": "ABX-PUBLIC",
            "repeat": 0,
        }
        public_task = ("none", {"trial_id": "ABX-PUBLIC"}, 0)
        sealed_record = {
            "enforcer": "benchmark_pdp_v3",
            "trial_id": "ABX-DECRYPTED-MUST-NOT-DRIVE-RESUME",
            "sealed_record_id": "sealed-record-opaque-17",
            "repeat": 1,
        }
        sealed_task = (
            "benchmark_pdp_v3",
            {
                "record_id": "sealed-record-opaque-17",
                "trial_id": "ABX-INDEX-MUST-NOT-WIN",
            },
            1,
        )
        self.assertEqual(
            run_eval._episode_key(public_record),
            run_eval._task_episode_key(public_task),
        )
        self.assertEqual(
            run_eval._episode_key(sealed_record),
            run_eval._task_episode_key(sealed_task),
        )
        completed = {
            run_eval._episode_key(public_record),
            run_eval._episode_key(sealed_record),
        }
        pending = [
            task for task in (public_task, sealed_task)
            if run_eval._task_episode_key(task) not in completed
        ]
        self.assertEqual(pending, [])

        def broken_record_key(record):
            return record["enforcer"], record["trial_id"], record["repeat"]

        self.assertNotEqual(
            broken_record_key(sealed_record),
            run_eval._task_episode_key(sealed_task),
            "the test must expose a resume implementation keyed by plaintext ID",
        )


class TestAggregateTamperRejection(_RunHarness):
    def setUp(self):
        super().setUp()
        error, _output, self.raw_path = self._invoke(
            "acceptance-evidence-model", _reference_run
        )
        self.assertIsNone(error)
        self.manifest_path = Path(str(self.raw_path) + ".manifest.json")
        self.manifest = json.loads(
            self.manifest_path.read_text(encoding="utf-8")
        )
        self.records = [
            json.loads(line)
            for line in self.raw_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        validation = aggregate._validate_manifest(
            copy.deepcopy(self.manifest),
            self.raw_path,
            str(LAB_ROOT / "catalog" / "core_v2.jsonl"),
            copy.deepcopy(self.records),
        )
        self.assertTrue(validation["complete"])

    def _assert_invalid(self, manifest, records, pattern, raw_path=None):
        with self.assertRaisesRegex(ValueError, pattern):
            aggregate._validate_manifest(
                manifest,
                raw_path or self.raw_path,
                str(LAB_ROOT / "catalog" / "core_v2.jsonl"),
                records,
            )

    @staticmethod
    def _decoding_observation(records):
        fields = (
            "api_mode", "request_temperature", "request_temperature_sent",
            "request_seed_sent", "request_enable_thinking",
            "request_enable_thinking_sent", "reasoning_effort",
            "request_reasoning_sent", "request_parallel_tool_calls",
            "request_parallel_tool_calls_sent",
        )
        return sorted({
            json.dumps(
                {key: response.get(key) for key in fields},
                sort_keys=True,
                separators=(",", ":"),
            )
            for record in records
            for response in record.get("model_responses", [])
        })

    def _resign_result(self, manifest):
        payload = copy.deepcopy(manifest["result_attestation_payload"])
        for field in tuple(payload):
            if field == "transport_abort":
                payload[field] = manifest["transport"]["abort"]
            elif field in manifest:
                payload[field] = manifest[field]
        manifest["result_attestation_payload"] = payload
        manifest["result_attestation"] = sign_attestation(
            payload,
            load_signing_key(self.signing_key_path),
            purpose="accessbench-result-v1",
        )

    def _resign_pre_run(self, manifest):
        manifest["config_commitment"] = hashlib.sha256(
            json.dumps(
                manifest["config"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        payload = copy.deepcopy(manifest["pre_run_attestation_payload"])
        payload["config_commitment"] = manifest["config_commitment"]
        manifest["pre_run_attestation_payload"] = payload
        manifest["pre_run_attestation"] = sign_attestation(
            payload,
            load_signing_key(self.signing_key_path),
            purpose="accessbench-pre-run-v1",
        )
        manifest["result_attestation_payload"]["pre_run_payload_sha256"] = (
            manifest["pre_run_attestation"]["payload_sha256"]
        )

    def _materialize_records(self, records, name):
        rechained = []
        previous = None
        for index, record in enumerate(records):
            unsigned = {
                key: value for key, value in record.items()
                if key not in CHAIN_FIELDS
            }
            rebuilt = chain_record(
                unsigned,
                chain_index=index,
                previous_record_sha256=previous,
            )
            previous = rebuilt["record_sha256"]
            rechained.append(rebuilt)
        raw_path = self.temp / name
        raw_path.write_text("".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in rechained
        ), encoding="utf-8")
        return raw_path, rechained, previous

    def _refresh_manifest_for_records(
        self, manifest, raw_path, records, chain_head
    ):
        manifest["raw_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        manifest["raw_chain_head_sha256"] = chain_head
        manifest["completed_episode_n"] = len(records)
        manifest["error_episode_n"] = sum("error" in record for record in records)
        manifest["observed_response_models"] = sorted({
            str(response.get("model"))
            for record in records
            for response in record.get("model_responses", [])
            if response.get("model")
        })
        manifest["response_metadata_complete"] = all(
            bool(record.get("model_responses"))
            and all(
                response.get("id") and response.get("model")
                for response in record.get("model_responses", [])
            )
            for record in records
            if "error" not in record
        )
        response_ids = [
            str(response["id"])
            for record in records
            for response in record.get("model_responses", [])
            if response.get("id")
        ]
        manifest["provider_response_ids_unique"] = bool(
            manifest["response_metadata_complete"]
            and response_ids
            and len(response_ids) == len(set(response_ids))
        )
        sessions = []
        session_shape_valid = True
        for record in records:
            if "error" in record:
                continue
            record_sessions = {
                response.get("client_episode_session_id")
                for response in record.get("model_responses", [])
                if response.get("client_episode_session_id")
            }
            if len(record_sessions) != 1:
                session_shape_valid = False
            else:
                sessions.append(next(iter(record_sessions)))
        manifest["client_episode_sessions_unique"] = bool(
            session_shape_valid and len(sessions) == len(set(sessions))
        )
        manifest["observed_system_fingerprints"] = sorted({
            str(response.get("system_fingerprint"))
            for record in records
            for response in record.get("model_responses", [])
            if response.get("system_fingerprint")
        })
        manifest["observed_decoding_requests"] = self._decoding_observation(
            records
        )
        self._resign_result(manifest)

    def test_semantic_decoding_tamper_fails_even_after_rechain_and_resign(self):
        records = copy.deepcopy(self.records)
        rechained = []
        previous = None
        for index, record in enumerate(records):
            for response in record["model_responses"]:
                response["request_parallel_tool_calls"] = True
            unsigned = {
                key: value for key, value in record.items()
                if key not in CHAIN_FIELDS
            }
            rebuilt = chain_record(
                unsigned,
                chain_index=index,
                previous_record_sha256=previous,
            )
            previous = rebuilt["record_sha256"]
            rechained.append(rebuilt)
        tampered_raw = self.temp / "decoding-tamper.jsonl"
        tampered_raw.write_text("".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in rechained
        ), encoding="utf-8")
        manifest = copy.deepcopy(self.manifest)
        manifest["raw_sha256"] = hashlib.sha256(
            tampered_raw.read_bytes()
        ).hexdigest()
        manifest["raw_chain_head_sha256"] = previous
        manifest["observed_decoding_requests"] = self._decoding_observation(
            rechained
        )
        self._resign_result(manifest)
        self._assert_invalid(
            manifest,
            rechained,
            "parallel tool calls off",
            raw_path=tampered_raw,
        )

        temperature_records = copy.deepcopy(self.records)
        temperature_records[0]["model_responses"][0][
            "request_temperature"
        ] = 0.75
        temperature_raw, temperature_records, head = self._materialize_records(
            temperature_records, "temperature-tamper.jsonl"
        )
        temperature_manifest = copy.deepcopy(self.manifest)
        self._refresh_manifest_for_records(
            temperature_manifest, temperature_raw, temperature_records, head
        )
        self._assert_invalid(
            temperature_manifest,
            temperature_records,
            "temperature|decoding",
            raw_path=temperature_raw,
        )

        seed_records = copy.deepcopy(self.records)
        target_trial = seed_records[0]["trial_id"]
        for record in seed_records:
            if record["trial_id"] == target_trial:
                record["request_seed"] = 123456789
        seed_raw, seed_records, head = self._materialize_records(
            seed_records, "seed-tamper.jsonl"
        )
        seed_manifest = copy.deepcopy(self.manifest)
        self._refresh_manifest_for_records(
            seed_manifest, seed_raw, seed_records, head
        )
        self._assert_invalid(
            seed_manifest,
            seed_records,
            "request seed|decoding",
            raw_path=seed_raw,
        )

    def _responses_mode_run(self, name, *, reasoning_sent=False,
                            enable_thinking=None):
        # Rewrite the chat-mode evidence into the shape the Responses adapter
        # records: no chat thinking control, seed not transmitted, reasoning
        # field recorded separately. Rechain and resign everything so only
        # the semantic checks can reject it.
        records = copy.deepcopy(self.records)
        rechained = []
        previous = None
        for index, record in enumerate(records):
            for response in record["model_responses"]:
                response["api_mode"] = "responses"
                response["request_seed_sent"] = False
                response["request_reasoning_sent"] = reasoning_sent
                response.pop("request_enable_thinking", None)
                response.pop("request_enable_thinking_sent", None)
                if enable_thinking is not None:
                    response["request_enable_thinking"] = enable_thinking
            unsigned = {
                key: value for key, value in record.items()
                if key not in CHAIN_FIELDS
            }
            rebuilt = chain_record(
                unsigned,
                chain_index=index,
                previous_record_sha256=previous,
            )
            previous = rebuilt["record_sha256"]
            rechained.append(rebuilt)
        raw_path = self.temp / f"{name}.jsonl"
        raw_path.write_text("".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in rechained
        ), encoding="utf-8")
        manifest = copy.deepcopy(self.manifest)
        manifest["config"]["resolved_api_mode"] = "responses"
        self._resign_pre_run(manifest)
        self._refresh_manifest_for_records(
            manifest, raw_path, rechained, previous
        )
        return manifest, rechained, raw_path

    def test_responses_mode_evidence_is_accepted_without_a_chat_thinking_control(self):
        manifest, records, raw_path = self._responses_mode_run("responses-ok")
        validation = aggregate._validate_manifest(
            copy.deepcopy(manifest),
            raw_path,
            str(LAB_ROOT / "catalog" / "core_v2.jsonl"),
            copy.deepcopy(records),
        )
        self.assertTrue(validation["complete"])

        manifest, records, raw_path = self._responses_mode_run(
            "responses-reasoning", reasoning_sent=True
        )
        self._assert_invalid(
            manifest, records, "reasoning transmission", raw_path=raw_path
        )

        manifest, records, raw_path = self._responses_mode_run(
            "responses-thinking", enable_thinking=True
        )
        self._assert_invalid(
            manifest, records, "unconfigured thinking", raw_path=raw_path
        )

    def test_exact_matrix_is_recomputed_instead_of_trusting_signed_counts(self):
        missing_raw, missing_records, head = self._materialize_records(
            copy.deepcopy(self.records[1:]), "missing-episode.jsonl"
        )
        missing_manifest = copy.deepcopy(self.manifest)
        missing_manifest["duplicate_episode_key_n"] = 0
        self._refresh_manifest_for_records(
            missing_manifest, missing_raw, missing_records, head
        )
        self._assert_invalid(
            missing_manifest,
            missing_records,
            "episode matrix|expected episode|missing episode",
            raw_path=missing_raw,
        )

        duplicate = copy.deepcopy(self.records[0])
        for response in duplicate["model_responses"]:
            response["id"] = str(response["id"]) + "-duplicate"
            response["client_episode_session_id"] = (
                str(response["client_episode_session_id"]) + "-duplicate"
            )
        duplicate_raw, duplicate_records, head = self._materialize_records(
            [*copy.deepcopy(self.records), duplicate], "duplicate-episode.jsonl"
        )
        duplicate_manifest = copy.deepcopy(self.manifest)
        duplicate_manifest["duplicate_episode_key_n"] = 0
        self._refresh_manifest_for_records(
            duplicate_manifest, duplicate_raw, duplicate_records, head
        )
        self._assert_invalid(
            duplicate_manifest,
            duplicate_records,
            "episode matrix|duplicate episode",
            raw_path=duplicate_raw,
        )

    def test_unresolved_transport_identity_and_raw_tampering_are_rejected(self):
        unresolved = copy.deepcopy(self.manifest)
        unresolved["unresolved_episode_keys"].append({
            "enforcer": "none", "reference_id": "ABX-MISSING", "repeat": 0
        })
        unresolved["unresolved_episode_n"] = 1
        unresolved["unresolved_episode_keys_sha256"] = hashlib.sha256(
            json.dumps(
                unresolved["unresolved_episode_keys"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._resign_result(unresolved)
        self._assert_invalid(
            unresolved, copy.deepcopy(self.records), "unresolved or unexpected"
        )

        transport = copy.deepcopy(self.manifest)
        transport["transport"]["exhausted_episode_attempts"].append({
            "recorded_at": "2026-08-21T00:00:00+00:00",
            "enforcer": self.records[0]["enforcer"],
            "reference_id": self.records[0]["trial_id"],
            "repeat": self.records[0]["repeat"],
            "attempt_n": 3,
            "exception_type": "RateLimitError",
            "status_code": 429,
            "provider_code": "sk-secret-provider-code",
            "message": "OPENAI_API_KEY=sk-secret-in-history",
            "message_sha256": "a" * 64,
        })
        transport["exhausted_episode_attempt_n"] = 1
        transport["exhausted_episode_attempts_sha256"] = hashlib.sha256(
            json.dumps(
                transport["transport"]["exhausted_episode_attempts"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._resign_result(transport)
        self._assert_invalid(
            transport,
            copy.deepcopy(self.records),
            "transport failure|secret|unexpected field",
        )

        identity = copy.deepcopy(self.manifest)
        for configured in identity["config"][
            "built_in_enforcement_identities"
        ]:
            if configured["id"] == "accessbench-benchmark-pdp":
                configured["version"] = "999"
        for observed in identity["observed_enforcement_identities"]:
            if observed["id"] == "accessbench-benchmark-pdp":
                observed["version"] = "999"
        self._resign_pre_run(identity)
        self._resign_result(identity)
        self._assert_invalid(
            identity,
            copy.deepcopy(self.records),
            "configured built-in enforcement identity|enforcement identity",
        )

        raw_records = copy.deepcopy(self.records)
        raw_records[0]["final_answer"] = "tampered after signing"
        self._assert_invalid(
            copy.deepcopy(self.manifest), raw_records, "chain digest mismatch"
        )


@unittest.skipUnless(BASH_MAJOR >= 4, BASH_TOO_OLD)
class TestRunpodControlAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.root = self.temp / "repo"
        self.runpod = self.root / "tools" / "runpod"
        self.lab = self.root / "environment_lab"
        self.runpod.mkdir(parents=True)
        (self.lab / "results_raw").mkdir(parents=True)
        for name in (
            "models.sh", "serve.sh", "sweep.sh", "preflight_model.py"
        ):
            shutil.copy2(REPO_ROOT / "tools" / "runpod" / name, self.runpod / name)
        self.key = self.temp / "signing.key"
        self.key.write_text("test-only", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _sweep(self, hold_file: Path):
        environment = {
            **os.environ,
            "HARNESS_PY": sys.executable,
            "ACCESSBENCH_SIGNING_KEY": str(self.key),
            "ACCESSBENCH_HARNESS_GIT_COMMIT": "acceptance-commit",
            "ACCESSBENCH_HARNESS_GIT_DIRTY": "no",
            "DRY_RUN": "1",
            "HOLD_FILE": str(hold_file),
            "HF_HOME": str(self.temp / "hf"),
        }
        return subprocess.run(
            [TEST_BASH, str(self.runpod / "sweep.sh"), "qwen32"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_status_is_fresh_and_hold_stops_before_next_serve(self):
        status = self.lab / "results_raw" / "sweep_status.txt"
        status.write_text("STALE DONE FROM PRIOR INVOCATION\n", encoding="utf-8")
        hold = self.temp / "no-hold"
        first = self._sweep(hold)
        self.assertEqual(first.returncode, 0, first.stderr)
        current = status.read_text(encoding="utf-8")
        self.assertNotIn("STALE DONE", current)
        self.assertIn("SWEEP start", current)
        archives = list((self.lab / "results_raw" / "logs").glob(
            "sweep-status-before-*.txt"
        ))
        self.assertTrue(archives)
        self.assertIn("STALE DONE", archives[0].read_text(encoding="utf-8"))

        hold.write_text("hold", encoding="utf-8")
        second = self._sweep(hold)
        self.assertEqual(second.returncode, 0, second.stderr)
        held_status = status.read_text(encoding="utf-8")
        self.assertIn("HOLD before qwen32", held_status)
        self.assertNotIn("DRY: serve", second.stdout)

    def test_serve_is_offline_revision_pinned_and_roster_excludes_bulk_files(self):
        fake_bin = self.temp / "bin"
        fake_bin.mkdir()
        capture = self.temp / "serve-capture.txt"
        fake_vllm = fake_bin / "vllm"
        fake_vllm.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n%s\\n%s\\n' \"$HF_HUB_OFFLINE\" "
            "\"$TRANSFORMERS_OFFLINE\" \"$*\" > \"$CAPTURE_PATH\"\n",
            encoding="utf-8",
        )
        fake_vllm.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "CAPTURE_PATH": str(capture),
            "HF_HOME": str(self.temp / "hf"),
        }
        served = subprocess.run(
            [TEST_BASH, str(self.runpod / "serve.sh"), "qwen32"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(served.returncode, 0, served.stderr)
        offline, transformers, arguments = capture.read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual((offline, transformers), ("1", "1"))
        self.assertIn(
            "--revision 9216db5781bf21249d130ec9da846c4624c16137",
            arguments,
        )

        roster = subprocess.run(
            [
                TEST_BASH, "-c",
                'source "$1"; printf "%s\\n%s\\n" '
                '"${DOWNLOAD_EXCLUDE[llama70]}" "${DOWNLOAD_EXCLUDE[gptoss]}"',
                "_", str(self.runpod / "models.sh"),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

        def exclusions_are_safe(lines):
            return (
                "original/*" in lines[0]
                and "original/*" in lines[1]
                and "metal/*" in lines[1]
            )

        self.assertTrue(exclusions_are_safe(roster))
        self.assertFalse(
            exclusions_are_safe(["", "metal/*"]),
            "the assertion must reject a roster that re-downloads bulk files",
        )


if __name__ == "__main__":
    unittest.main()
