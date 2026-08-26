"""Unit tests for the RunPod model/tool compatibility preflight."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "runpod" / "preflight_model.py"
SPEC = importlib.util.spec_from_file_location("runpod_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preflight)


class _FakeAgent:
    provider_model = "test/model"

    def __init__(self, *args, **kwargs):
        self.response_metadata = []
        self.turn = 0

    def complete(self, messages):
        self.turn += 1
        self.response_metadata.append({
            "id": f"response-{self.turn}",
            "model": self.provider_model,
            "request_parallel_tool_calls": False,
            "request_parallel_tool_calls_sent": True,
        })
        if self.turn == 1:
            name = "read_resource"
            arguments = '{"resource_id":"preflight-resource"}'
        else:
            name = "finish"
            arguments = '{"final_answer":"preflight-ok"}'
        call = SimpleNamespace(
            id=f"call-{self.turn}",
            function=SimpleNamespace(name=name, arguments=arguments),
        )

        class Message:
            tool_calls = [call]

            @staticmethod
            def model_dump():
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }],
                }

        return SimpleNamespace(message=Message())


class TestRunpodPreflight(unittest.TestCase):
    def _run(self, provider_model):
        _FakeAgent.provider_model = provider_model
        output = io.StringIO()
        with patch.object(preflight, "SubjectAgent", _FakeAgent), patch.object(
            sys,
            "argv",
            ["preflight_model.py", "--model", "test/model", "--attempts", "1"],
        ), patch("sys.stdout", output):
            result = preflight.main()
        return result, json.loads(output.getvalue())

    def test_pass_requires_valid_tool_call_and_provider_model_identity(self):
        result, report = self._run("test/model")
        self.assertEqual(result, 0)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["attempts"][0]["valid"])
        self.assertEqual(
            report["attempts"][0]["first_turn_tool_call_names"],
            ["read_resource"],
        )
        self.assertEqual(
            report["attempts"][0]["second_turn_tool_call_names"],
            ["finish"],
        )
        self.assertTrue(
            report["attempts"][0]["single_tool_call_control_bound"]
        )

    def test_provider_model_mismatch_fails_closed(self):
        result, report = self._run("wrong/model")
        self.assertEqual(result, 2)
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["attempts"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
