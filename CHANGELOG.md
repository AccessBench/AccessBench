# Changelog

Versions follow semantic versioning. The catalog carries its own data
versions (scenario v5, oracle v2, panel `accessbench-core-v2-development-600`);
those move independently of the software version.

## [Unreleased]

- `TRUSTED_KEYS.json` removed from the repository. No key is admitted; every
  result is self-signed by the operator who ran it, and `run --full` says so.
  The registry mechanism (`trust add-key` / `trust list`, env-var override)
  stays in the code for when an outside party holds part of it.
- The AWS KMS sealed-bank track is documented as not in use: `boto3` leaves
  the `production` extra and `requirements-lock.txt` (the `kms-aws` extra
  remains opt-in), and the design, scope, integrity, validation, limits and
  dictionary pages say the sealed pack and cloud key do not exist yet.
- Legacy v0.1 files removed: `scenarios/` (family YAML and builders),
  `scripts/.env.example`, and the retired `fig-headline.svg`.
- README points at the core-v3 six-model batch on accessbench.io as
  single-pass, unfrozen-harness evidence outside the results of record.
- SECURITY.md no longer describes the repository as pre-1.0.

## [1.0.0] - 2026-08-26

First public release: the runnable harness, the reviewed 600-case
development bank, the Benchmark PDP as the clearly labeled reference decision
point, the AuthZEN enforcement contract, a zero-cost demo, one canonical run
path for models and for PDP implementers, self-contained result bundles with
a one-command verifier, the exact result tables and limits, and the release
files (LICENSE, NOTICE, SECURITY.md, CONTRIBUTING.md, CITATION.cff, issue
forms). Results stay bound to their recorded commits; no change to the
runner, aggregator, PDPs, oracle, catalog, scoring, or evidence semantics.

Folded in since 0.17.1, in merge order:

- Judge calibration: `run --full` calibrates the Anti-Cheat Judge on a fixed
  fixture corpus before the run and stops under 0.90 precision.
- Trusted-key registry: `TRUSTED_KEYS.json` plus `trust add-key` /
  `trust list`; admitting a key is a git-recorded act, not a runtime env var;
  env vars remain an additive override.
- Isolation observers: network and filesystem isolation checks graded during
  a real run.
- Clean-machine path: demo no longer builds the 104 MB construction matrix;
  macOS skips the two Bash-4 pod tests with a reason; setup docs match the
  code.
- Bank review attestation: `attest-review` / `verify-review` bind a named
  reviewer's decision to the exact 600-prompt bank.
- Filesystem-isolation observer no longer treats macOS `/private` temp paths
  as the repository's private directory; `dev` extra now brings pytest.
- Backend decisions: a client-side exception before any provider response
  routes to the transport retry path instead of scoring against the model;
  trust wording says maintainer-controlled registry, never "independently
  trusted"; report.html names where the forbidden-half column comes from
  (later removed below).
- Dashboard: `/report?run_id=` serves a bundle's report.html; run ids are
  validated before any path is built.
- Docs: KMS, sealed bank and admission are the later sealed track, never a
  v1 gate; one paired pass is the protocol; shared 9 cases listed in
  docs/08-limits.md; README headline is the seven-model result of record.
- Legacy package removal: the root `accessbench/` package, its test suite,
  the old judge-calibration fixtures in `calibration/`, and the legacy demo
  scripts are gone; one run path, not two. The KMS-sealing CLI surface
  (`seal-aws`, `inspect-sealed`, `verify-sealed-aws`) is removed as well;
  `accessbench_env/sealed_assets.py` stays in place but unreachable from the
  CLI, since the corpus stays public/development for now rather than sealed.
- Dashboard trimmed to the real run browser; the legacy SSE-driven live-demo
  feed (which hard-depended on the now-removed `accessbench/` package) is
  gone.
- Report.html's forbidden-half column, which recomputed exact-match
  exfiltration over the forbidden half live instead of reading it from
  `summary.json`, is removed until it is a real schema field.
- `TRUSTED_KEYS.json` key relabeled to its actual owner.
- Setup guide: documented the catalog-generate step CI already runs before
  `pytest`, missing before and now the first line of the test-suite section.
- Release files: CITATION.cff, issue forms, PR template, CONTRIBUTING fixes.

Not in this release: sealed evaluation bank and admission tooling (the later
Live Verified track), a leaderboard or ranking, submission portal,
compliance claims, enterprise integrations beyond the AuthZEN seam.

## [0.17.1] - 2026-08-22

- docs/11-results.md: replication table updated for the third local pass
  (six models at three passes, Qwen3-Coder at two accepted); leak flips
  reported per arm (none behind the Benchmark PDP in any pass; one subset
  case in the no-enforcement arm for three models). Numbers of record
  (primary pass) unchanged.

## [0.17.0] - 2026-08-22

Public command layer and documentation route. No change to the runner,
aggregator, PDPs, oracle, catalog, scoring, or evidence semantics; results
stay bound to their recorded commits.

- `accessbench` console command (alias of `accessbench-env`, both installed).
- `accessbench demo`: zero-cost offline grader proof with no arguments.
- `accessbench run`: `--enforcement benchmark` as the public name for the
  Benchmark PDP (recorded as `benchmark_pdp_v3` in evidence); `--resume RAW`;
  one preflight before any inference (signing key, credentials, disk, PDP
  conformance, model tool use; `--skip-model-preflight`); hosted spend
  estimate from measured token volume; exact resume command on failure;
  smoke and full runs labeled unmistakably; every run ends in one
  self-contained result directory (summary.json, report.html, run.json,
  evidence/, VERIFY.txt).
- `accessbench verify RESULT_DIR [--raw PATH] [--json]`: digest, completeness,
  hash chain, signatures, score recomputation, integrity sidecar; PASS/FAIL
  per check, exit 0 only when all pass; works on legacy result directories
  through `--raw`.
- report.html: readable result page, Charter, percent first, vertical paired
  bars, configuration and verification sections.
- README rewritten as a router around demo / run / verify with two reader
  paths (model-only users, PDP implementers); "gold standard" claim removed;
  docs/04 rebuilt around the same path and the bundle layout; docs/10 gains
  "Verify a result bundle"; wording corrected across docs 02/03/06/07/08/10
  (telemetry and network statement, self-signed not independently validated,
  no-enforcement arm wording, reference decision point).
- Dashboard labels `benchmark_pdp_v3` as Benchmark PDP (v2 as Benchmark PDP v2).
- TRADEMARKS.md removed; the project rests on Apache 2.0 only.
- Tests: 25 new (verify, bundle, preflight, alias, resume, demo defaults);
  suite 193 passed plus the two known macOS-bash runpod cases.

## [0.16.7] - 2026-08-22

Results page and cross-model figure for the 0.16.5 track; no run, prompt,
oracle, PDP, threshold or result-schema change. Results stay bound to 2040bcf.

- docs/11-results.md: numbers of record for seven models behind
  benchmark_pdp_v3 (primary pass), fixed protocol, replication passes and the
  trial rule, the shared 9 cases, where the evidence lives.
- docs/assets/fig-models.svg: cross-model figure, vertical grey/scarlet pairs
  with the exfiltration panel above the work-completed-safely panel; hosted
  references first, then open weights alphabetically; refusal under each model.
- tools/make_diagrams.py: model pairs default to benchmark_pdp_v3 and select
  the first complete core run per model (the primary pass), skipping smoke
  runs; gpt-5.6 Sol short name. Other figures regenerated from the current kit
  (token block only).
- README: 11. Results in the docs list and a pointer under the headline figure.

## [0.16.6] - 2026-08-22

Housekeeping after the 0.16.5 model track; no run, prompt, oracle, PDP,
aggregate or threshold change.

- `eval/run_eval.py`: resume now refuses a prior manifest written under a
  different manifest schema version (the schema string is the module constant
  `MANIFEST_SCHEMA_VERSION`), so a raw from an older runner cannot be
  continued under the newer evidence rules while keeping its old label. Test
  added to the smoke/resume suite.
- `tools/runpod/bootstrap.sh`: the download exclude list expands safely when
  empty under `set -u` on Bash 4.0 to 4.3 (the pod's Bash 5 was unaffected).

## [0.16.5] - 2026-08-21

- `eval/aggregate.py`: the v4 per-response decoding check rejected every
  Responses-API record (`provider request enabled unconfigured thinking`)
  because the Responses adapter records no chat-style `request_enable_thinking`
  control; the OpenAI Responses API has no such parameter. Found by the
  gpt-4o 50-case pilot under 0.16.4, which the aggregate refused. For
  `api_mode == "responses"` the check now rejects an enabled thinking control
  and requires `request_reasoning_sent` to match the protocol's
  `reasoning_effort` (none unless configured); the chat-completions check is
  unchanged. Regression test added to the aggregate tamper suite (accept the
  Responses shape, reject a reasoning request or an enabled thinking control).
  No run, prompt, oracle, PDP or threshold change.

## [0.16.4] - 2026-08-21

Pre-run repair set for the cross-model trial track. No prompt string, oracle
label, success assertion, case identifier, result threshold or test tolerance
changed; the 600 core prompts are byte-identical to 0.16.3 (prompt-set digest
`4df53604...aba611`).

- Benchmark PDP v3 (`accessbench_env/benchmark_pdp_v3.py`, id
  `benchmark_pdp_v3`, identity `accessbench-benchmark-pdp` version 3). It
  extends v2 with record-grained recent-authentication enforcement that reads
  `max_auth_age_seconds` from the observed label, rejects a future-dated
  authentication as stale, and validates every event view against a closed
  schema so malformed input fails closed. v2 stays registered and runnable.
  `tools/runpod/sweep.sh` and `serve.sh` now default to v3 and the docs name
  v3 as the reference enforcement input.
- The observed defense view is built by the generator, not by the sandbox at
  run time. `record_selector`, `source_tenant`, `requires_approval` and
  `max_auth_age_seconds` are materialized into each `defense_view` item in
  `catalog/core_v2.jsonl`, `validate.py` checks them against the underlying
  facts and profile, and `sandbox.py` passes the catalog item through
  unchanged. The AuthZEN event view advertises `accessbench-event-view-v2`.
  Catalog and contamination manifests carry the new catalog digests.
- Subject agent. Both adapters send `parallel_tool_calls=false` explicitly
  (the Responses adapter previously sent `true`) and record the request
  control in response metadata. An assistant turn that issues more than one
  tool call ends the episode as a capability failure before any tool runs.
- `eval/run_eval.py` writes `accessbench-live-run-v4` manifests. Resume and
  scheduling key on the opaque sealed record id before any plaintext trial
  alias. Exhausted transport attempts are recorded with only the exception
  class, a numeric HTTP status and SHA-256 digests of the provider code and
  message; the transport breaker no longer aborts the process. The runner
  reconstructs the full episode matrix at the end, prints `INCOMPLETE` and
  exits 3 when it is not exact (the raw stays resumable), and prints `DONE`
  only for a complete matrix.
- `eval/aggregate.py` independently rebuilds the expected episode matrix from
  the manifest and rejects duplicate, missing or unexpected episodes; for v4
  manifests it also binds the fixed decoding protocol, checks per-response
  request evidence (api mode, temperature, seed, thinking, parallel tool
  calls) and schema-validates the transport history so a fully re-signed raw
  with tampered decoding, matrix or secret-bearing transport fields is refused.
- RunPod tooling. `preflight_model.py` is a two-turn check (one `read_resource`
  call, tool result in history, one `finish` call, unique response ids, exact
  provider model, `parallel_tool_calls=false` bound; schema
  `accessbench-model-preflight-v2`). `sweep.sh` starts a fresh, run-stamped
  status file, archives the previous one, and honors a `HOLD` file before
  serving the next model. `serve.sh` serves offline (`HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1`) from the pinned snapshot; `models.sh` and
  `bootstrap.sh` exclude bulk `original/` and `metal/` files from downloads.
- Tests: independent pre-run acceptance suites
  (`test_prerun_acceptance_policy_protocol.py`,
  `test_prerun_acceptance_evidence_runpod.py`) with faulty doubles, tampered
  re-signed evidence and negative controls; `test_benchmark_pdp_v3.py`;
  fixtures updated for the v4 manifest. The two RunPod shell control tests
  need GNU Bash 4+ (`ACCESSBENCH_TEST_BASH` on macOS).

## [0.16.3] - 2026-08-21

- Figures. Twelve diagrams now stand where the `[INSERT ...]` placeholders and
  the two hand-typed flow charts were, a flagship visual sits at the top of the
  README, and a square mark is available for an icon. They are generated, not
  drawn: `tools/svgkit.py` holds the shared palette and arrow vocabulary,
  `tools/make_hero.py` and `tools/make_diagrams.py` emit the SVGs into
  `docs/assets/`, and `tools/flatten_svg.py` produces a copy for design tools.
- No figure paints a background, so each one sits on the page rather than on a
  card of its own. Every colour is a token with a light value and a dark value
  carried inside the file, so one SVG follows the reader's theme. Type is
  Charter throughout.
- Two placeholders were removed rather than filled, because the paragraph next
  to each already said the same thing: the bank grid in the README (it is drawn
  in 03 Scope, where the contract lives) and the second copy of the paired
  experiment in 02 Methodology (it is drawn in 01 Design).

- Reset the cross-model trial track. Responses requests send temperature zero
  to GPT-4o, omit unsupported seed, and record every decoding field actually
  sent. Reasoning configurations explicitly record omitted controls.
- Qwen-only `enable_thinking` template arguments no longer reach Mistral. The
  RunPod sweep now requires a successful protocol tool call before a full run
  and has an explicit diagnostic `SMOKE_TRIALS` pilot mode.
- Every full-run local subject binds an exact weight snapshot, loading mode,
  vLLM version, serving-command digest, orchestration digest and preflight
  digest. The manifest also binds client/runtime versions, system fingerprints,
  and stable built-in PDP identities.
- Resume discovery is fail closed: the runner emits `RAW_PATH` before inference
  and the sweep never guesses from the newest global raw. A manifest-model check
  runs before aggregation.
- DeepSeek-Coder-V2-Lite is retained only as a diagnostic incompatibility. The
  full-run roster uses Qwen3-Coder-30B-A3B in its place. The Llama tool
  template is pinned to vLLM 0.27.1 and verified by SHA-256.
- Synchronized the environment-lab package version with the repository version.

## [0.16.2] - 2026-08-21

- `tools/runpod/sweep.sh`: unattended local-model sweep for one GPU box
  (serve, wait for readiness, run the paired benchmark with resume,
  aggregate with provider `vllm`, stop the server, next key).
- `tools/runpod/models.sh`: `mistral24` pins `--tokenizer-mode mistral`;
  new keys `llama70` (Meta Llama 3.3 70B, fp8 at load) and `qwencoder30`
  (Qwen3-Coder-30B-A3B); `ORDER_80GB` is the five keys that run on a
  CUDA 12.8 / vLLM 0.11 box, with the CUDA-13-only keys listed separately.
- `tools/runpod/bootstrap.sh`: uses the `hf` CLI, fetches the Llama tool chat
  template, default `HF_HOME=/workspace/hf`.
- `tools/runpod/README.md`: roster table, run order, budget, hosted fallback.

## [0.16.1] - 2026-08-20

- **The Benchmark PDP returns a decision for a malformed request instead of
  raising.** A decision point reads claims it did not write. A token whose
  expiry is a string, a catalog entry that is null, a posture object of the
  wrong shape: all of them now produce allow, deny, or rewrite. Unreadable
  claims are treated as absent and the checks that depend on them are skipped,
  never read as a pass. Found by fuzzing the gate with 72 malformed event views
  before committing to a multi-model run, where a raise would have shown up as
  a voided episode rather than an obvious failure.
- No measured result changed. Both banks reproduce byte-identically after the
  hardening: development 600 at 542 pass / 26 forbidden leak / 249 held and
  done / 25 held and lost, held-out 10,800 at 8,027 / 657 / 2,695 / 2,048.
- `tests/test_benchmark_pdp_v2.py` gains the malformed-request suite: 17
  mutations across all four governed boundaries, each called twice so carried
  state is exercised too.

## [0.16.0] - 2026-08-20

- **The Benchmark PDP withholds by removing, not by denying.** A second
  revision, `benchmark_pdp_v2` (`environment_lab/accessbench_env/benchmark_pdp_v2.py`),
  is now the default enforcement input. Records a subject may not have are
  removed from the payload at the source and again at every exit and the
  rest goes through; a stale session is step-up at record grain instead of a
  dead read; an outbound payload that already omits every withheld record is
  allowed as written; an encoded payload that carries a withheld value is
  refused. Token checks a resource server performs before reading (expiry,
  effective revocation, audience, scope to this app and this task) still
  refuse outright. Tenant isolation and approval receipts are enforced at
  record grain. The first revision stays in the ladder as `benchmark_pdp` so
  the 2026-08-19 run remains comparable.
- Measured on the deterministic reference path over all 600 cases, hardest
  agent, zero model cost: governed pass 542/600 (first revision 294, no
  enforcement 300), forbidden-case exfiltration 26/300 (first revision 111,
  none 300), forbidden cases held with the work still done 249/300 (first
  revision 0). The 7 permitted cases it misses and the 26 leaks it cannot
  close are itemised in docs/08-limits.md; every remaining leak is hidden by
  the label-noise model or is a credential-only trap with labels identical
  to the required record.
- Live, gpt-4o, one pass, 600 cases per arm: governed pass 484/600 = 80.7% (no
  enforcement 325/600 = 54.2%); forbidden-case exfiltration 15/300 (none
  227/300), a 93% cut; forbidden cases held with the work still done 226 (none
  66); permitted work 258/300 against 259/300, inside noise; refusal 3.2% in
  both arms; 1,200 episodes, 0 errors. Raw
  `results_raw/20260820T220841022959Z-gpt-4o.jsonl`, summary
  `results/20260820-221315-openai-gpt-4o/summary.json`. For reference, the
  first revision on 2026-08-19 measured 42.7% pass and 16.8% exfiltration
  against 46.7% and 39.1% for its control. The 15 residual leaks are 9
  sparse-label classification traps and 6 auth-age traps whose labels match
  the required record; the 59 forbidden cases held but lost are 21 deliveries
  that failed the artifact check (the same title-omission pattern as the
  control's own losses), 20 abandonments or refusals after a correct
  request-level denial on credential-only traps, and 18 where the agent gave
  up after a redaction or the posture removed the required record.
- Two structural fields join the observed label at sandbox time, the way
  `record_selector` did in 0.14.0: `source_tenant` (which tenant owns the
  record, from the occurrence) and `requires_approval` (from the record's
  policy metadata). Neither is part of the label-noise model, neither names
  which record the task needs or what is planted there, and catalog digests
  are unchanged. Ratified by the maintainer on 2026-08-20 and now part of the
  event-view contract, joining `record_selector` and `enterprise_profile`.
- The portability test now also forbids the generator's tag vocabulary
  (`synthetic-sensitive`, `approved-summary`) in any Benchmark PDP source,
  for both revisions, because a gate that read those tags would be reading
  the answer key.
- The conformance suite passes against `benchmark_pdp_v2` hosted behind the
  AuthZEN seam, including the egress probe; labels carried on an outbound
  event itself now bind exactly like records seen at the source.
- `tests/test_benchmark_pdp_v2.py`: 23 tests pinning source admission,
  record-grain step-up, token checks, exit control, encoded-payload refusal,
  and that no denial across the whole panel carries case material.

## [0.15.0] - 2026-08-20

- **The protocol runs the fixed bank once per arm, not three times.** A run is
  now 1,200 episodes instead of 3,600, so a full paired comparison costs a
  third of what it did. `PROTOCOL_K` is 1.
- The change was measured before it was made. Five paired 600-case runs from
  2026-08-19 (ten arms, 18,000 episodes) were re-scored with each single pass
  treated as the whole run. Largest gap between a one-pass estimate and the
  three-pass estimate: 0.32 points on exact-match exfiltration, 1.2 points on
  task completion, 1.1 points on governed task pass. Smallest arm gap those
  numbers are used to describe: 12.6 points. Exfiltration outcomes disagreed
  across passes on 0 to 4 cases out of 600. docs/02-methodology.md section 10.4
  carries the table.
- `--repeats N` is a new diagnostic setting on `eval/run_eval.py` for anyone
  who wants the case-level flakiness profile. It is recorded in the manifest,
  multiplies cost by N, and is not the reportable protocol configuration.
- The stable-case-pass block gains `stability_measurable`. It is false under
  the one-pass protocol, which is how a reader knows that `intermittent_n: 0`
  means "not measured" rather than "no flaky cases".
- Aggregation no longer rejects a run with fewer than three passes; the floor
  is one. Nothing else about scoring changed: the pass conjunction, the
  deterministic oracle, the denominators, and the anti-cheat checks are the
  same.
- The enforcement-decision-consistency check does not lose teeth. It works on
  event-view digests that already recur thousands of times inside a single
  pass, and the conformance suite still probes an identical view twice offline
  at no model cost.
- Documentation updated throughout (01-design, 02-methodology section 10.4,
  03-scope, 04-setup, 06-integrity, 07-validation, 09-dictionary,
  10-replication) and the dashboard no longer prints a repeat multiplier when
  there is one pass.

## [0.14.0] - 2026-08-19

- The Benchmark PDP (`--enforcement benchmark_pdp`), the default enforcement
  input when a vendor brings none: record-level redaction at read
  (unauthorized records removed, nothing added, no markers), egress redaction,
  a constructive structured 403 with a permitted alternative only when nothing
  can be delivered, and identity checks (revocation, expiry, authentication
  age, token audience, scope) evaluated where the credential is presented. It
  honors the tenant policy profile instead of hard-coding one posture, and a
  portability test forbids benchmark-specific knowledge in its source.
- Denial secrecy proved across all 600 cases: every structured 403 is checked
  against its own case; a denial says which door is shut and never describes
  the room.
- Two event-view additions, both attached at sandbox time so the frozen
  catalog and its digests did not move: each observed label carries
  `record_selector`, and `decision_context.enterprise_profile` carries the
  tenant policy posture.
- Enforcement decision consistency is now state aware: a stateful gate's
  variation is reported as such instead of flagged as a failure, and every
  arm records its `state_scope`.
- Scoring safety: a harness error never inflates a result (excluded from the
  violation denominator and the stable-pass numerator, counted where a reader
  sees it); a late refusal cannot launder a leak; every summary reports
  `violation_denominator_share`.
- `label_governance_v2`, a sensitivity-scoped reference gate returning a
  structured fixed-vocabulary 403, ships alongside v1 so earlier runs stay
  comparable.
- The Anti-Cheat registry executor runs the closed 17-check registry against
  real runs and never invents a pass; oracle replay re-scored 200 episodes
  identically.
- The sealed lane passed an end-to-end dry run: opaque index, uniform
  records, selective decrypt, faithful round trip; the sealer refuses the
  public split.
- Runner hardening: transport and billing failures can no longer masquerade
  as model capability failures; a circuit breaker aborts cleanly and resume
  re-runs exactly what is missing; hosted-endpoint runs require
  `ACCESSBENCH_SPEND_APPROVED=yes`.
- Aggregation adds `per_macro_category` (per leak type stays primary); the
  percent formatter can no longer render a nonzero rate as zero.
- Dashboard: headline strip with the three numbers that carry the story, one
  bar pair per model-and-enforcement combination, readable gate names.
- First complete development-bank runs on three hosted models, 3,600 episodes
  each with zero error records; run-to-run variance on identical
  configurations measured at about 1.5 points of stable pass. Development
  bank, integrity Ineligible: internal measurement only, no model claim may
  be quoted.
- Cold start verified: a fresh clone with no private material installs,
  regenerates the construction matrix to the exact admitted digest, and
  passes the full test suite.

## [0.13.1] - 2026-08-19

- Dashboard became a run browser: run picker, eligibility badge, summary
  line, enforcement comparison table (percent first, counts beneath),
  leak-type grid, and a closing figure that draws every complete pair.

## [0.13.0] - 2026-08-19

- Runner hardened for long hosted runs: resume on the same configuration
  commitment with chain verification, per-episode retries with backoff,
  smoke mode for tiny cost and latency measurement runs (always ineligible).

## [0.12.0] - 2026-08-19

- Held-out matrix regenerated under scenario v5 and oracle v2; splits proved
  compatible and disjoint; contamination manifest rebuilt.

## [0.11.1] - 2026-08-19

- Navigation pass: the root README became the map, prototypes retired,
  serving kit moved under `tools/`.

## [0.11.0] - 2026-08-19

- `accessbench_env conformance --enforcement URL`: an AuthZEN pre-run check a
  vendor runs against its own decision point, ten checks over synthetic event
  views only, JSON report, non-zero exit on failure.

## [0.10.1] - 2026-08-19

- Percent-first everywhere: every metric shows the percent large and the
  count as subtext; refusal rate sits beside each headline figure.

## [0.10.0] - 2026-08-19

- Rewrite is redaction-only: a rewritten payload may remove or mask words but
  may not add any word absent from the attempted payload; violations are
  denied at scoring time and counted.
- Every recorded event carries `event_view_sha256`; aggregation recomputes
  enforcement decision consistency and writes `enforcement_conduct` per arm.
- The Anti-Cheat registry moves to v2 (17 checks), fail-closed until attested.

## [0.9.0] - 2026-08-19

First release-candidate line for the public 1.0.0.

- Two-input runner (`--model`, `--enforcement`) with an automatic
  no-enforcement arm; no other benchmark inputs.
- Core-v2 600-case development panel (scenario v5, oracle v2) with executable
  shortcut controls bound into the manifest.
- AuthZEN 1.0 enforcement seam; a composed identity plus data reference
  enforcer behind the same seam.
- Signed, predecessor-bound episode chain; Ed25519 pre-run and final
  attestations; paired counterbalanced arms.
- Opaque record sealing; sealed runner and sealed aggregation, fail-closed.
- AccessBench Anti-Cheat: closed check registry, frozen Judge adapter
  (run-integrity only), Valid / Flagged / Ineligible with reason codes.
