# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Compatibility imports for the pre-v1 evidence-auditor module name.

New code imports :mod:`accessbench_env.anti_cheat_judge`. The official
component name is AccessBench Anti-Cheat Judge.
"""

from .anti_cheat_judge import (
    ANTI_CHEAT_JUDGE_PROMPT_SHA256,
    ANTI_CHEAT_JUDGE_PROMPT_VERSION,
    ANTI_CHEAT_JUDGE_RESPONSE_SCHEMA,
    ANTI_CHEAT_JUDGE_SYSTEM_PROMPT,
    anti_cheat_judge_binding,
    build_anti_cheat_judge_request,
    run_anti_cheat_judge,
)

AUDITOR_PROMPT_VERSION = ANTI_CHEAT_JUDGE_PROMPT_VERSION
AUDITOR_SYSTEM_PROMPT = ANTI_CHEAT_JUDGE_SYSTEM_PROMPT
AUDITOR_PROMPT_SHA256 = ANTI_CHEAT_JUDGE_PROMPT_SHA256
AUDITOR_RESPONSE_SCHEMA = ANTI_CHEAT_JUDGE_RESPONSE_SCHEMA
build_auditor_request = build_anti_cheat_judge_request
run_evidence_auditor = run_anti_cheat_judge
auditor_binding = anti_cheat_judge_binding

__all__ = [
    "ANTI_CHEAT_JUDGE_PROMPT_SHA256",
    "ANTI_CHEAT_JUDGE_PROMPT_VERSION",
    "ANTI_CHEAT_JUDGE_RESPONSE_SCHEMA",
    "ANTI_CHEAT_JUDGE_SYSTEM_PROMPT",
    "AUDITOR_PROMPT_SHA256",
    "AUDITOR_PROMPT_VERSION",
    "AUDITOR_RESPONSE_SCHEMA",
    "AUDITOR_SYSTEM_PROMPT",
    "anti_cheat_judge_binding",
    "auditor_binding",
    "build_anti_cheat_judge_request",
    "build_auditor_request",
    "run_anti_cheat_judge",
    "run_evidence_auditor",
]
