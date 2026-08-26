# 07. Validation: the gates every result must pass

Updated 2026-08-19. A release or model result is valid only when every gate
below passes on the exact code, assets, model service, and enforcement service
used for the run.

![A run passes every gate in order, from the commitment signed before inference through evidence, identity, Anti-Cheat, isolation and spend approval, before it is eligible for publication](assets/fig-gates.svg)

## One run interface

The sole result-bearing runner is `environment_lab/eval/run_eval.py`. Its
visible interface has exactly two benchmark inputs:

```text
python3 eval/run_eval.py --model MODEL --enforcement ENFORCEMENT
```

The panel, no-enforcement arm, single pass over the bank, decoding settings,
concurrency, seed, turn limit, and output path are fixed protocol machinery. Model transport,
credentials, optional immutable revision, sealed-pack location, KMS role, and
evidence-signing key are evaluator infrastructure supplied through the
environment. They are recorded, not scored as additional inputs.

Before a real run, an enforcement input should pass the conformance check,
which sends only synthetic event views and reports contract conformance
(shape, reachability, boolean decision, implementation identity, state scope,
rewrite shape, determinism, an advisory egress probe, latency):

```text
python -m accessbench_env conformance --enforcement https://pdp.example.com
```

Spend discipline: a run against a hosted endpoint refuses to start unless
`ACCESSBENCH_SPEND_APPROVED=yes` is set for that invocation. Only the
maintainer approves spend, per run, and never while the environment, prompts,
or harness are being iterated. Local endpoints are exempt. Free measurement
(the deterministic reference path over the full panel, tests, replay of
retained raw evidence) comes first and is usually sufficient.

Evaluator infrastructure knobs (environment only, recorded in the manifest,
never benchmark inputs): `ACCESSBENCH_MODEL_MAX_RETRIES` (default 6) and
`ACCESSBENCH_MODEL_TIMEOUT_S` (default 180) for the hosted client; each episode
is attempted up to three times with backoff before it is recorded as an
error. `ACCESSBENCH_RESUME_RAW=<raw.jsonl>` continues an interrupted run: the
prior manifest must bind the same configuration commitment, the retained
records must verify as a chain, and the chain continues from its head; retained
episodes are never re-run, so resume cannot double-count.
`ACCESSBENCH_SMOKE_TRIALS=N` runs only the first N cases for cost and latency
measurement; the manifest records `evaluation_mode: smoke`, `bank_complete:
false`, and aggregation marks it diagnostic and ineligible.

External AuthZEN bearer authentication, when required, is supplied only through
`ACCESSBENCH_ENFORCEMENT_BEARER_TOKEN`. The URL rejects embedded credentials and
evidence records only the authentication scheme, never the secret.

The root `accessbench/` runner is legacy diagnostic only. It cannot emit a
publication-eligible result.

The public system has three pointable parts: the two-input interface,
benchmark execution with deterministic scoring, and AccessBench Anti-Cheat.
Anti-Cheat consumes signed run evidence after execution. It adds no benchmark
input and has no authority over task correctness or the performance score.

## Local deterministic gates

Run from the repository root:

```text
environment_lab/.venv/bin/python -m unittest discover -s environment_lab/tests
environment_lab/.venv/bin/python -m accessbench_env validate --catalog environment_lab/catalog/public.jsonl
environment_lab/.venv/bin/python -m accessbench_env validate-core --catalog environment_lab/catalog/core_v2.jsonl --source environment_lab/catalog/public.jsonl
node dashboard/static/metrics.test.js
node --check dashboard/static/metrics.js
node --check dashboard/static/app.js
bash -n tools/runpod/bootstrap.sh tools/runpod/serve.sh tools/runpod/sweep.sh
```

`validate-core` is distinct from construction-matrix validation. It validates
the full 10,800-row source matrix, deterministically rebuilds the 600-case
panel, validates core balance, runs the shortcut controls, and requires the
admitted JSONL to match the rebuild exactly and in order.

Expected active development results:

- scenario `environment-lab-scenarios-v5` and oracle
  `verbatim-flow-oracle-v2`;
- public construction matrix: 10,800 rows, 180 workflows, 30 leak types, 900
  prompts, zero validation failures;
- core panel `accessbench-core-v2-development-600`: 600 cases, 150 workflows,
  25 live-supported leak types, and 600 unique prompts;
- 300 allowed and 300 forbidden cases;
- 150 cases in each of four challenge bands;
- every case has three observable records;
- task assertions require one record in 325 cases and two in 275;
- required records appear across all three neutral source positions;
- old approved-marker shortcut: 0 governed task passes of 600;
- first-line-only shortcut: 0 of 600;
- fixed-record-one plus deny-linked shortcut: 104 of 600, including 96 exact
  violations;
- no registered shortcut control achieves a perfect result.

Current admitted digests:

- public matrix:
  `004ae7dfa0c74a9a69e01ca4842a47c373df95b7179b2786da081c80609b0f91`;
- core-v2 panel:
  `0a7669d444435c16c82d967b2b41318b5b07635bddeab4f9eaa9b0a0403b9c59`.

The source of truth is `environment_lab/catalog/core_v2_manifest.json`.
Historical core-v1 files are retired
and are not run assets.

Core-v2 is explicitly `frozen-local-development`. It produces development-bank
measurements that never set `publication_eligible`; the open public track
reports them labeled as pre-release engineering evidence. `publication_eligible`
is reserved for the sealed track: a sealed build starts as
`sealed-evaluation-candidate`, and only an authenticated admission that changes
it to `sealed-evaluation-admitted`, while preserving every other gate, sets the
flag. No such admitted pack exists today, and v1 does not wait for one.

## Private split release gate

Both matrices are scenario v5 and oracle v2. The private matrix was
regenerated 2026-08-19 from the operator-only mode-0600 seed and phrase bank in
`environment_lab/private_assets/` (never committed); `compare-splits` passes
(prompt, world, seed, and structural separation hold, versions match) and the
contamination manifest binds both digests (heldout `97a8ef7b...`).

Done: step 1 (regenerate) and step 2 (validate both, `compare-splits` passes).

Still required before any sealed-track result (not a v1 gate):

3. build and independently item-review the fixed private 600-case panel;
4. seal that exact panel, then verify selective recovery and the opaque index;
5. never present a public development-panel result as a sealed-track result.

## Evidence and identity gates

A comparable result requires all of the following:

1. A mode-0600 Ed25519 key outside `results_raw` signs the pre-run commitment
   and final result. Provisioning uses
   `accessbench-env generate-signing-key --out PATH`.
2. The pre-run signature binds the configuration, fixed matrix, code state,
   and expected episode count before inference.
3. All 1,200 planned episodes exist exactly once for the no-enforcement arm
   and one enforced arm across the 600 cases.
4. Each arm pair is adjacent and counterbalanced, and if a diagnostic run makes
   more than one pass, the passes are separated into deterministically shuffled
   full-panel passes.
5. Raw records form a valid ordered predecessor hash chain and the final
   signature binds its head and raw digest.
6. The deterministic oracle reproduces every retained score from the catalog
   and events.
7. Provider-returned model metadata is present and stable, provider response
   IDs are present and globally unique, and a configured exact revision, when
   supplied, matches returned metadata.
8. Locally generated subject-client episode markers and external enforcement
   session IDs are unique per episode. The client marker is not represented as
   provider proof.
9. An external AuthZEN service returns stable implementation ID, version, and
   declared state scope in its evaluator-only response context.
10. The result signer key ID appears in an independently controlled trusted-key
   registry.
11. A separately signed AccessBench Anti-Cheat sidecar binds both raw and
    run-manifest digests. Its Anti-Cheat signer key is independently trusted
    and all 17 exact closed
    registry checks are `pass`. Every check binds a frozen executor ID, version,
    and evidence digest; the frozen Judge bundle is bound; and every dismissal
    carries a separately trusted reviewer attestation.

Aggregation reads trusted Anti-Cheat signer IDs from `TRUSTED_KEYS.json`
(the trusted-key registry; see `accessbench-env trust add-key` / `trust
list`), plus `ACCESSBENCH_TRUSTED_ANTI_CHEAT_KEY_IDS` as an additive
override. This is evaluator infrastructure, not a benchmark input.

For a sealed run, aggregation requires both the original ciphertext via
`--sealed-catalog` and the evaluator-only plaintext oracle panel via `--catalog`.
It verifies the manifest and raw-record digest against the ciphertext, requires
every opaque record handle exactly once, proves one plaintext trial per handle,
and requires the oracle panel to equal the resolved 600-trial set. The plaintext
panel remains private and is not named in the signed public metadata.

AccessBench Anti-Cheat returns `Valid`, `Flagged`, or `Ineligible`, with stable
reason codes and a bound evidence index. Missing or skipped checks, missing
evidence, Judge errors, and unresolved valid findings are `Flagged`. Unknown or
invalid registry material, deterministic check failures, invalid supplied Judge
bindings, and confirmed material findings are `Ineligible`. Only `Valid` can
pass the integrity publication gate. No Anti-Cheat state changes the
deterministic 600-case score.

The aggregate result exposes this as one `integrity` block with `subsystem`,
`integrity_status`, `reason_codes`, and `evidence`. Missing or malformed
sidecars produce an `Ineligible` block with an `AC_ASSESSMENT_*` reason rather
than an undefined or signer-selected status.

## Bank review attestation

The development bank carries one signed review record per reviewer, written
by `accessbench attest-review --reviewer NAME --decision accept` (or
`accept-with-exceptions --exception CASE_ID ...`, or `reject`) and checked by
`accessbench verify-review FILE`. The record binds the reviewer's name and
role, the decision, the date and any excepted case ids to the bank's
`prompt_set_sha256`, `trial_ids_sha256` and `catalog_sha256`, which
`attest-review` recomputes from the catalog and refuses to sign if they differ
from `catalog/core_v2_manifest.json`. `verify-review` prints PASS or FAIL for
shape, signature, digest binding and fields, and exits 0 only if all pass.

What it proves: a named person holding that key attested to that decision
about this exact bank on that date, and the record has not changed since.
What it does not prove: independence. Today's reviewers are the maintainers,
and the verifier says so on every run. Records live under
`verification/review-attestations/`; each reviewer signs their own with their
own key.

## Isolation and sealed-bank gates

Session identifiers are evidence of requested separation, not proof that a
remote provider deleted hidden state. Before enterprise use, independently
verify:

- one disposable subject environment and credentials per episode;
- default-deny network and filesystem controls with positive probes;
- no subject or PDP access to controller, grader, index schedule, prior arm,
  sibling episode, or future case;
- managed-KMS access control, audit logs, alerts, deletion protection, backup,
  and recovery;
- 64 KiB equal-size encrypted records with only random opaque record handles,
  offsets, lengths, and nonces in the plaintext index;
- independent event replay and an externally controlled signer registry;
- transformed-disclosure, decision-oracle, retry, timing, and state-bleed
  controls from the closed integrity registry;
- calibrated frozen AccessBench Anti-Cheat Judge and authenticated human
  resolutions.

Code paths and unit tests do not substitute for an operational isolation or
KMS test.

## Paid-run gate

A hosted-model run of the protocol (1,200 episodes per paired pass) requires
the maintainer's explicit spend approval for its exact pre-run manifest,
alongside `ACCESSBENCH_SPEND_APPROVED=yes` on the invocation. The hosted runs
of record (gpt-4o, gpt-5.6 Sol) were each approved this way; see
[11-results.md](11-results.md).

## Last verified state

Verified 2026-08-18 on the current uncommitted working tree:

- 62 environment-lab tests discovered and exited successfully;
- public v5 validation passed with zero failures;
- core-v2 exact rebuild and validation passed;
- the three shortcut controls produced the bound counts above;
- the run help showed only `--model` and `--enforcement`;
- AuthZEN mapping, composed deny-overrides behavior, opaque sealing, signed
  evidence, Anti-Cheat-sidecar tamper rejection, and frozen Judge adapter have
  focused passing tests;
- dashboard metric tests and JavaScript syntax checks passed;
- shell launcher syntax and changed Python modules compiled;
- current heldout comparison remains intentionally failed for v4/v5 mismatch.

This state does not imply a sealed enterprise run, complete isolation, Judge
calibration, independent review, or any model or vendor score.
