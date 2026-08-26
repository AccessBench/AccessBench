# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for the bank review attestation: `attest-review` / `verify-review`."""
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

from accessbench_env import cli, review_attestation, trust_registry  # noqa: E402
from accessbench_env.evidence import generate_signing_key, load_signing_key  # noqa: E402

RECORDED = json.loads((LAB_ROOT / "catalog" / "core_v2_manifest.json").read_text())


class BankDigestTests(unittest.TestCase):
    def test_digests_match_the_recorded_manifest(self):
        digests = review_attestation.bank_digests()
        for field in review_attestation.BOUND_FIELDS:
            self.assertEqual(digests[field], RECORDED[field], field)
        self.assertEqual(digests["panel_id"], "accessbench-core-v2-development-600")
        self.assertEqual(len(digests["prompt_set_sha256"]), 64)

    def test_a_catalog_that_differs_from_the_manifest_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            manifest = tmp / "manifest.json"
            edited = dict(RECORDED, catalog_sha256="0" * 64)
            manifest.write_text(json.dumps(edited))
            with self.assertRaises(ValueError):
                review_attestation.bank_digests(manifest=manifest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key_path = self.tmp / "reviewer.pem"
        generate_signing_key(self.key_path)
        self.key = load_signing_key(self.key_path)
        self.digests = review_attestation.bank_digests()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _payload(self, **overrides):
        kwargs = dict(reviewer="Test Reviewer", decision="accept", date="2026-08-22")
        kwargs.update(overrides)
        return review_attestation.build_payload(self.digests, **kwargs)

    def test_sign_then_verify_passes_and_is_labeled_maintainer_review(self):
        record = review_attestation.sign_review(self._payload(), self.key)
        result = review_attestation.verify_review(record)
        self.assertTrue(result["ok"], result)
        statuses = {item["check"]: item["status"] for item in result["checks"]}
        self.assertEqual(statuses["signature"], "PASS")
        self.assertEqual(statuses["digest binding"], "PASS")
        self.assertEqual(statuses["fields"], "PASS")
        self.assertEqual(statuses["signing key"], "INFO")
        self.assertIn("not make the review independent", json.dumps(result["checks"]))
        self.assertEqual(record["payload"]["review_method"], review_attestation.REVIEW_METHOD)
        self.assertIn("not independent", record["payload"]["review_method"])

    def test_tampered_decision_fails_the_signature(self):
        record = review_attestation.sign_review(self._payload(), self.key)
        record["payload"]["decision"] = "reject"
        result = review_attestation.verify_review(record)
        self.assertFalse(result["ok"])
        self.assertEqual([i["status"] for i in result["checks"] if i["check"] == "signature"], ["FAIL"])

    def test_record_bound_to_another_bank_fails_digest_binding(self):
        payload = self._payload()
        payload["prompt_set_sha256"] = "f" * 64
        record = review_attestation.sign_review(payload, self.key)
        result = review_attestation.verify_review(record)
        self.assertFalse(result["ok"])
        statuses = {item["check"]: item["status"] for item in result["checks"]}
        self.assertEqual(statuses["signature"], "PASS")
        self.assertEqual(statuses["digest binding"], "FAIL")

    def test_decision_and_exception_rules(self):
        with self.assertRaises(ValueError):
            self._payload(decision="accept", exceptions=["ABX-1"])
        with self.assertRaises(ValueError):
            self._payload(decision="accept-with-exceptions")
        with self.assertRaises(ValueError):
            self._payload(decision="maybe")
        with self.assertRaises(ValueError):
            self._payload(date="yesterday")
        payload = self._payload(decision="accept-with-exceptions", exceptions=["ABX-2", "ABX-1", "ABX-1"])
        self.assertEqual(payload["exceptions"], ["ABX-1", "ABX-2"])
        self.assertEqual(payload["reviewed_range"], "1-600")

    def test_registry_listing_is_reported_as_admission_not_independence(self):
        record = review_attestation.sign_review(self._payload(), self.key)
        key_id = record["attestation"]["key_id"]
        result = review_attestation.verify_review(record, trusted_key_ids={key_id})
        note = [i["detail"] for i in result["checks"] if i["check"] == "signing key"][0]
        self.assertIn("not independence", note)

    def test_write_refuses_to_overwrite(self):
        record = review_attestation.sign_review(self._payload(), self.key)
        path = review_attestation.write_review(record, self.tmp / "out")
        self.assertEqual(path.name, "test-reviewer-2026-08-22.json")
        with self.assertRaises(FileExistsError):
            review_attestation.write_review(record, self.tmp / "out")


class ReviewCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key_path = self.tmp / "reviewer.pem"
        generate_signing_key(self.key_path)
        self._patch = patch.object(trust_registry, "DEFAULT_REGISTRY_PATH", self.tmp / "TRUSTED_KEYS.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_attest_then_verify_round_trip(self):
        args = cli.parser().parse_args([
            "attest-review", "--reviewer", "PJ Mullin", "--decision", "accept",
            "--date", "2026-08-22", "--signing-key", str(self.key_path),
            "--out-dir", str(self.tmp / "records"),
        ])
        out = StringIO()
        with redirect_stdout(out):
            cli.command_attest_review(args)
        text = out.getvalue()
        self.assertIn("not independent validation", text)
        record_path = self.tmp / "records" / "pj-mullin-2026-08-22.json"
        self.assertTrue(record_path.exists())
        summary = json.loads(text[: text.rindex("}") + 1])
        self.assertEqual(summary["prompt_set_sha256"], RECORDED["prompt_set_sha256"])

        vargs = cli.parser().parse_args(["verify-review", str(record_path)])
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            cli.command_verify_review(vargs)
        self.assertEqual(stop.exception.code, 0)
        self.assertIn("result: VERIFIED", out.getvalue())
        self.assertIn("not independent validation", out.getvalue())

        record = json.loads(record_path.read_text())
        record["payload"]["reviewer"]["name"] = "Someone Else"
        record_path.write_text(json.dumps(record))
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            cli.command_verify_review(cli.parser().parse_args(["verify-review", str(record_path)]))
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("result: FAILED", out.getvalue())

    def test_unknown_exception_id_is_refused(self):
        args = cli.parser().parse_args([
            "attest-review", "--reviewer", "PJ Mullin", "--decision", "accept-with-exceptions",
            "--exception", "ABX-NOT-A-CASE", "--signing-key", str(self.key_path),
            "--out-dir", str(self.tmp / "records"),
        ])
        with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as stop:
            cli.command_attest_review(args)
        self.assertIn("not in the catalog", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
