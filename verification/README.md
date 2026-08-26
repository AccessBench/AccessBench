# verification (private)

How the 600 prompts were authored, audited, reviewed, and turned into the
runtime prompt module and the core catalog. Everything here is private: it
contains the scored bank in plaintext.

- `author_prompt_bank.py`, `revise_prompt_openings.py`: authoring.
- `audit_prompt_candidates.py`, `PROMPT_BANK_V1_CANDIDATE_AUDIT.md`: audit.
- `build_human_review_ledger.py`, `prompt_bank_human_review_v1.jsonl`,
  `PROMPT_BANK_HUMAN_REVIEW_V1.md`: the ledger; independent human signoff is
  recorded here and is still pending.
- `build_core_prompt_module.py`, `build_core_catalog.py`,
  `prove_core_solvability.py`: build and prove the runtime module and panel.
