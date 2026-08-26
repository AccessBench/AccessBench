# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for `accessbench-env trust add-key` / `trust list`."""
from __future__ import annotations

import json
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

from accessbench_env import cli, trust_registry  # noqa: E402

KEY_A = "a" * 64


class TrustCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.registry_path = self.tmp / "TRUSTED_KEYS.json"
        self._patch = patch.object(trust_registry, "DEFAULT_REGISTRY_PATH", self.registry_path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_key_then_list_round_trips(self):
        args = cli.parser().parse_args([
            "trust", "add-key", "--key-id", KEY_A, "--owner", "Test Owner",
            "--purpose", "accessbench-pre-run-v1", "--purpose", "accessbench-result-v1",
        ])
        with redirect_stdout(StringIO()) as out:
            cli.command_trust_add_key(args)
        self.assertIn(KEY_A, out.getvalue())

        list_args = cli.parser().parse_args(["trust", "list"])
        with redirect_stdout(StringIO()) as out:
            cli.command_trust_list(list_args)
        keys = json.loads(out.getvalue())
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["key_id"], KEY_A)
        self.assertEqual(keys[0]["owner"], "Test Owner")
        self.assertEqual(
            sorted(keys[0]["purposes"]),
            ["accessbench-pre-run-v1", "accessbench-result-v1"],
        )

    def test_list_on_an_empty_registry_says_so_plainly(self):
        args = cli.parser().parse_args(["trust", "list"])
        with redirect_stdout(StringIO()) as out:
            cli.command_trust_list(args)
        self.assertIn("no admitted keys", out.getvalue())

    def test_rejects_an_invalid_key_id_via_the_cli(self):
        args = cli.parser().parse_args([
            "trust", "add-key", "--key-id", "too-short", "--owner", "Test",
            "--purpose", "accessbench-pre-run-v1",
        ])
        with self.assertRaises(ValueError):
            cli.command_trust_add_key(args)

    def test_unknown_purpose_is_rejected_by_argparse_itself(self):
        with self.assertRaises(SystemExit):
            cli.parser().parse_args([
                "trust", "add-key", "--key-id", KEY_A, "--owner", "Test",
                "--purpose", "not-a-real-purpose",
            ])


if __name__ == "__main__":
    unittest.main()
