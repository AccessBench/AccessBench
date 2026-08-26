# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accessbench_env.trust_registry import (
    add_key,
    list_keys,
    load_registry,
    registry_trusted_key_ids,
    trusted_key_ids_for,
)

KEY_A = "a" * 64
KEY_B = "b" * 64


class TrustRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "TRUSTED_KEYS.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_is_an_empty_registry_not_an_error(self):
        registry = load_registry(self.path)
        self.assertEqual(registry["keys"], [])

    def test_add_key_then_query_by_purpose(self):
        add_key(
            KEY_A, ["accessbench-anti-cheat-assessment-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        self.assertEqual(
            registry_trusted_key_ids("accessbench-anti-cheat-assessment-v1", path=self.path),
            {KEY_A},
        )
        self.assertEqual(
            registry_trusted_key_ids("accessbench-human-resolution-v1", path=self.path),
            set(),
        )

    def test_rejects_a_non_sha256_key_id(self):
        with self.assertRaises(ValueError):
            add_key(
                "not-a-real-key-id", ["accessbench-pre-run-v1"],
                owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
            )

    def test_rejects_an_unknown_purpose(self):
        with self.assertRaises(ValueError):
            add_key(
                KEY_A, ["some-made-up-purpose"],
                owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
            )

    def test_rejects_re_registering_the_same_key_silently(self):
        add_key(
            KEY_A, ["accessbench-pre-run-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        with self.assertRaises(ValueError):
            add_key(
                KEY_A, ["accessbench-result-v1"],
                owner="A. Operator", added_at="2026-08-23T00:00:01Z", path=self.path,
            )

    def test_a_key_can_carry_multiple_purposes(self):
        add_key(
            KEY_A,
            ["accessbench-pre-run-v1", "accessbench-result-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        self.assertEqual(
            registry_trusted_key_ids("accessbench-pre-run-v1", path=self.path), {KEY_A}
        )
        self.assertEqual(
            registry_trusted_key_ids("accessbench-result-v1", path=self.path), {KEY_A}
        )

    def test_list_keys_reflects_what_was_added(self):
        add_key(
            KEY_A, ["accessbench-pre-run-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        add_key(
            KEY_B, ["accessbench-result-v1"],
            owner="B. Operator", added_at="2026-08-23T00:00:01Z", path=self.path,
        )
        ids = {entry["key_id"] for entry in list_keys(self.path)}
        self.assertEqual(ids, {KEY_A, KEY_B})

    def test_env_var_is_an_additive_override_not_a_replacement(self):
        add_key(
            KEY_A, ["accessbench-pre-run-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        with patch.dict("os.environ", {"ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS": KEY_B}):
            ids = trusted_key_ids_for(
                "accessbench-pre-run-v1", "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
                path=self.path,
            )
        self.assertEqual(ids, {KEY_A, KEY_B})

    def test_registry_alone_is_used_when_the_env_var_is_unset(self):
        add_key(
            KEY_A, ["accessbench-pre-run-v1"],
            owner="A. Operator", added_at="2026-08-23T00:00:00Z", path=self.path,
        )
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS", None)
            ids = trusted_key_ids_for(
                "accessbench-pre-run-v1", "ACCESSBENCH_TRUSTED_SIGNING_KEY_IDS",
                path=self.path,
            )
        self.assertEqual(ids, {KEY_A})


if __name__ == "__main__":
    unittest.main()
