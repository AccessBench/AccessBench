# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from accessbench_env.evidence import (
    chain_record,
    generate_signing_key,
    load_signing_key,
    sign_attestation,
    verify_attestation,
    verify_record_chain,
)


class EvidenceTests(unittest.TestCase):
    def test_record_chain_detects_reorder_rewrite_and_omission(self):
        records = []
        previous = None
        for index, value in enumerate(("a", "b", "c")):
            record = chain_record(
                {"value": value},
                chain_index=index,
                previous_record_sha256=previous,
            )
            records.append(record)
            previous = record["record_sha256"]
        self.assertEqual(verify_record_chain(records), previous)
        for changed in (
            [records[1], records[0], records[2]],
            [records[0], records[2]],
            [records[0], {**records[1], "value": "forged"}, records[2]],
        ):
            with self.assertRaises(ValueError):
                verify_record_chain(changed)

    def test_attestation_requires_expected_purpose_payload_and_trusted_key(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "signing.pem"
            key_id = generate_signing_key(key_path)
            private_key = load_signing_key(key_path)
            payload = {"raw_sha256": "a" * 64, "chain_head": "b" * 64}
            attestation = sign_attestation(
                payload, private_key, purpose="accessbench-result-v1"
            )
            self.assertEqual(
                verify_attestation(
                    payload,
                    attestation,
                    purpose="accessbench-result-v1",
                    trusted_key_ids={key_id},
                ),
                key_id,
            )
            with self.assertRaises(ValueError):
                verify_attestation(
                    {**payload, "chain_head": "c" * 64},
                    attestation,
                    purpose="accessbench-result-v1",
                    trusted_key_ids={key_id},
                )
            with self.assertRaises(ValueError):
                verify_attestation(
                    payload,
                    attestation,
                    purpose="accessbench-pre-run-v1",
                    trusted_key_ids={key_id},
                )
            with self.assertRaises(ValueError):
                verify_attestation(
                    payload,
                    attestation,
                    purpose="accessbench-result-v1",
                    trusted_key_ids={"0" * 64},
                )


if __name__ == "__main__":
    unittest.main()
