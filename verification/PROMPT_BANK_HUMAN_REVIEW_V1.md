# AccessBench v1 prompt review and human signoff ledger

Every prompt in the fixed local development bank received an item-level
automated semantic decision after automated vocabulary, structure, and
similarity checks. This is not independent human review. The same ledger
is the queue in which a named human reviewer must record signoff.

## Result

- Automated semantic decisions: 600 pass, 0 reject
- Independent human signoffs: 0 pass, 0 reject, 600 pending
- Read and passed without a recorded edit: 500
- Edited, reread, and passed: 100
- Workflows: 150
- Executable leak types: 25
- Prompts per executable leak type: 24

## Admission meaning

A semantic-review pass means the request is plausible enterprise language, preserves the
workflow source, destination, audience, and action, and does not state the
hidden access condition. It is a pre-review decision, not human signoff,
and it does not mean a model or enforcement layer passes the case. The
complete 600-row queue is in
`prompt_bank_human_review_v1.jsonl`.
