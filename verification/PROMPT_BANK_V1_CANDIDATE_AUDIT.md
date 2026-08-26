# AccessBench v1 candidate prompt audit

This report audits the newly authored 600-prompt candidate bank after
all 25 leak-type batches passed their local gates. No prompt is admitted
without a final human decision.

## Summary

- Prompts: 600
- Workflows: 150
- Executable leak types: 25
- Candidate for human review: 600
- Rewrite required: 0

Automated rewrite reasons:


Most common three-word openings:

- 9: `ahead of the`
- 9: `prepare for the`
- 7: `we re aligning`
- 6: `in preparation for`
- 5: `we need the`
- 4: `for the scheduled`
- 4: `at the upcoming`
- 4: `before the upcoming`
- 4: `prepare a customer`
- 3: `to prepare for`
- 3: `prepare the scheduled`
- 3: `we re coordinating`
- 3: `we re comparing`
- 3: `the support team`
- 3: `we re reconciling`
- 3: `we re consolidating`
- 2: `before the deployment`
- 2: `let s give`
- 2: `customer support has`
- 2: `the customer room`

Five-word phrases spanning at least four workflows:

- 19: `and share it in the`
- 18: `and post it in the`
- 15: `the private slack channel for`
- 15: `in the private slack channel`
- 14: `and add it to the`
- 14: `a drive document for the`
- 12: `it as a drive document`
- 11: `it in the private slack`
- 11: `in a drive document for`
- 11: `add it to the salesforce`
- 10: `as a drive document for`
- 9: `private slack channel for the`
- 9: `into a drive document for`
- 8: `work item is waiting for`
- 8: `to the salesforce account for`
- 8: `the slack connect channel for`
- 8: `the salesforce case for the`
- 8: `slack connect channel for the`
- 8: `it into a drive document`
- 8: `it in a drive document`
- 8: `in the slack connect channel`
- 8: `in the slack channel for`
- 8: `and post it to the`
- 7: `write it into a drive`
- 7: `the slack channel for the`
- 7: `share it in the slack`
- 7: `save it as a drive`
- 7: `post it in the private`
- 7: `it to the salesforce case`
- 7: `it in the slack connect`

## Per-prompt evidence

The complete prompt text, nearest-neighbor evidence, decision, and reasons
for all 600 prompts are in `prompt_bank_v1_candidates.jsonl`.
