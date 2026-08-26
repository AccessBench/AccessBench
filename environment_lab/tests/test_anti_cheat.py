# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
import unittest

from accessbench_env.anti_cheat import (
    FLAGGED,
    INELIGIBLE,
    VALID,
    anti_cheat_contract_fields,
    derive_anti_cheat_decision,
)


class AntiCheatContractTests(unittest.TestCase):
    def test_contract_separates_oracle_and_judge_authority(self):
        contract = anti_cheat_contract_fields()
        self.assertEqual(contract["subsystem"], "AccessBench Anti-Cheat")
        self.assertEqual(
            contract["academic_classification"],
            "hybrid benchmark-integrity assurance subsystem",
        )
        self.assertEqual(
            contract["authority"]["performance_score"],
            "deterministic_oracle",
        )
        self.assertEqual(
            contract["judge"]["academic_classification"],
            "LLM-as-a-Judge for run-integrity evaluation",
        )
        self.assertEqual(contract["judge"]["authority"], "run_integrity_only")
        self.assertNotIn("score", contract)

    def test_decision_vocabulary_is_valid_flagged_or_ineligible(self):
        status, reasons = derive_anti_cheat_decision({})
        self.assertEqual((status, reasons), (VALID, ["AC_VALIDATED"]))

        status, reasons = derive_anti_cheat_decision({
            "missing_checks": ["network_isolation"],
        })
        self.assertEqual(status, FLAGGED)
        self.assertEqual(reasons, ["AC_REQUIRED_CHECK_MISSING"])

        status, reasons = derive_anti_cheat_decision({
            "hard_failures": ["network_isolation"],
        })
        self.assertEqual(status, INELIGIBLE)
        self.assertEqual(reasons, ["AC_DETERMINISTIC_CHECK_FAILED"])

    def test_missing_judge_binding_flags_but_invalid_binding_is_ineligible(self):
        status, reasons = derive_anti_cheat_decision({
            "anti_cheat_judge_binding": {},
            "anti_cheat_judge_binding_errors": ["missing"],
        })
        self.assertEqual(status, FLAGGED)
        self.assertEqual(reasons, ["AC_JUDGE_BINDING_MISSING"])

        status, reasons = derive_anti_cheat_decision({
            "anti_cheat_judge_binding": {"judge_model": "model"},
            "anti_cheat_judge_binding_errors": ["invalid"],
        })
        self.assertEqual(status, INELIGIBLE)
        self.assertEqual(reasons, ["AC_JUDGE_BINDING_INVALID"])


if __name__ == "__main__":
    unittest.main()
