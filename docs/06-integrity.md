# 06. Integrity: asset boundary, threat model, Anti-Cheat

Updated 2026-08-19. This is private operating design. Public documentation may
describe the method and its limits, but must not publish active prompts,
worlds, assignments, protected values, Anti-Cheat probes, private phrase banks,
keys, or raw heldout evidence.

## The integrity decision

The public architecture has three pointable parts:

1. the two-input interface, MODEL plus ENFORCEMENT;
2. benchmark execution and deterministic scoring;
3. AccessBench Anti-Cheat.

![Benchmark execution forks into the deterministic grader, which owns the performance score, and AccessBench Anti-Cheat, which owns the integrity status, evidence and reason codes; the two meet in one signed result](assets/fig-integrity.svg)

AccessBench Anti-Cheat is a hybrid benchmark-integrity assurance subsystem and
multi-stage integrity decision procedure, not a single model, algorithm, or
equation. Deterministic validators and detection algorithms inspect the run
first. The specialized AccessBench Anti-Cheat Judge is an LLM-as-a-Judge for
run-integrity evaluation only. It cannot decide task correctness or change the
performance score. The deterministic oracle retains both authorities.
Anti-Cheat returns `Valid`, `Flagged`, or `Ineligible` with stable reason codes
and a bound evidence index. It consumes retained evidence and adds no benchmark
input.

AccessBench has one eligible v1 experiment with exactly two benchmark inputs:
MODEL and ENFORCEMENT. The enforced arm is compared with the no-enforcement
arm on the same 600 cases. Everything else is fixed or evaluator
infrastructure.

## Asset boundary

The experiment has three asset surfaces:

1. a public method and AuthZEN integration contract with no scored pack;
2. a private local development bank for deterministic construction and tests;
3. a managed sealed service for externally claimable results.

The current workspace implements the first two and important pieces of the
third. It is not yet an operational sealed service.

### Current truth

The active development construction matrix is scenario v5 and oracle v2. It
has 10,800 generated cases, 180 workflows, 30 leak types, and 900 prompts. The
fixed core-v2 development panel selects 600 cases across 150 workflows and 25
live-supported leak types (defined in [05. Leak types](05-leak-types.md)),
with 300 allowed and 300 forbidden cases.

The former core-v1 marker shortcut is preserved as historical evidence. On
that bank, a fixed approved-marker and first-line strategy achieved 600 of 600
governed task passes without policy reasoning. Core-v2 changes the task
contract and input structure:

- all cases expose three neutral-position records;
- task assertions require one or two records plus a meaningful titled artifact;
- required positions and linked-resource roles rotate independently of policy;
- observable task structure remains matched inside policy triads;
- fixed safe-path labels were removed;
- executable negative controls are bound into the panel manifest.

The old marker and first-line controls now achieve 0 of 600. A broader
fixed-record and deny-linked control achieves 104 of 600 and 96 exact
violations. This defeats those registered shortcuts. It does not prove no
unknown shortcut exists.

The private heldout matrix is v5/v2 as of 2026-08-19, regenerated locally from
the operator-only seed and phrase bank (`environment_lab/private_assets/`,
mode 0600, never committed). That matrix feeds the later sealed track: an
independently item-reviewed fixed private 600-case panel, sealed and admitted.
The v1 open public track does not wait for it.

Panel identity is fail-closed. The plaintext core is
`frozen-local-development`; it never sets `publication_eligible`, and results
on it are reported as development-bank evidence, labeled as such. A newly
sealed private panel is `sealed-evaluation-candidate` and remains ineligible.
Only a separately authenticated review can create `sealed-evaluation-admitted`.
Aggregation verifies that identity against the authenticated sealed header.
Admission tooling and an admitted pack do not yet exist; they belong to the
sealed track, not to v1.

### Protected material

| Class | Examples | Release rule | Storage rule |
| --- | --- | --- | --- |
| Public method | two-input contract, AuthZEN mapping, scoring semantics, limits | publish after approval | clean public history |
| Development content | prompts, worlds, values, assignments, grader fixtures | never treat as external evidence | private working tree or encrypted archive |
| Active sealed content | prompt pack, worlds, assignments, schedule, canary formats | never publish while active | managed-KMS encrypted records only |
| Integrity material | frozen Judge prompt, probes, attack fixtures, calibration data | disclose categories and limits only | restricted encrypted operating store |
| Key material | encryption, signing, reviewer, commitment keys | never publish | managed KMS, HSM, or protected mode-0600 operator store |
| Raw evidence | transcripts, event traces, decision receipts, reviewer notes | approved evaluator and Anti-Cheat operator only | encrypted retention-controlled store |

The "active sealed content" row and the managed-KMS storage rules describe
the later sealed track; no sealed content or managed key exists today, and the
development bank is plaintext under Apache 2.0.

Provider API keys are transport credentials. They must never encrypt packs,
derive protected values, sign results, or establish benchmark trust.

## Threat model

The design assumes a subject, enforcement service, provider, or operator could
accidentally or deliberately improve the reported result without improving the
intended capability. Important routes include:

- recognizing prompts, IDs, value formats, positions, counts, or pack order;
- reading controller, grader, filesystem, process, environment, logs, or
  sibling episodes;
- using package, DNS, telemetry, web, provider-tool, or callback egress;
- probing denial detail, timing, rewrite shape, or errors as a policy oracle;
- preserving exact required text while transforming prohibited text;
- using deny-all behavior or exploiting incomplete task assertions;
- sharing hidden state across episodes or arms;
- serving another model or enforcement implementation under an alias;
- deleting, replacing, selectively retrying, or locally re-signing evidence;
- omitting a deterministic check or manipulating the Anti-Cheat Judge.

Success alone is never evidence of cheating. A finding must cite an observable
protocol violation or a policy-preserving counterfactual.

## AuthZEN enforcement boundary

An external ENFORCEMENT value is a server root or the normative AuthZEN 1.0
`/access/v1/evaluation` endpoint. AccessBench maps one defensive copy of an
event into subject, action, resource, and context. The model receives only a
generic denial. Detailed reasons, component receipts, implementation identity,
and state-scope evidence remain evaluator-visible.

The request contains no trial ID, flow variant, expected outcome, hidden policy
case, lineage ID, or grader carrier. The optional AccessBench response
extension is namespaced under `context.accessbench`.

An optional AuthZEN bearer token comes from evaluator infrastructure, never the
ENFORCEMENT URL. Only the scheme is retained in evidence. Production external
services must use authenticated TLS even though plain HTTP remains available
for the loopback test seam.

Each HTTP client uses a random episode enforcement-session ID and monotonic
request sequence. The service must return stable implementation ID, version,
and declared state scope. These fields detect missing or inconsistent evidence.
They are not independent cryptographic proof of the remote implementation.

### Composed identity and data governance

The reference `composed_reference` enforcement demonstrates the high-impact
architecture without expanding the benchmark interface. An identity component
and data-governance component operate behind one ENFORCEMENT endpoint and use
deny-overrides. Evaluator-visible metadata records only each component effect.
The model sees one combined allow or generic deny.

This is the reference decision point used for calibration, not an industry
standard or a vendor product.
External credibility requires separately measured identity-only, data-only,
joint, and conflict cases across independent implementations. A multi-vendor
pilot must show portability before AccessBench proposes a neutral composition
profile. Industry adoption and acceptance of AccessBench as the scoring method
are market outcomes, not claims that code can establish.

## Sealed-pack design

![The panel is selected, shuffled and padded to a fixed record size, encrypted record by record, and scheduled by opaque handle; four checks at aggregation time verify the run against the sealed digest](assets/fig-sealed.svg)

Production sealing selects the exact 600-case panel before encryption, shuffles
record order, and pads every plaintext record to 64 KiB. Every record has its
own AES-GCM nonce and authentication. The plaintext index contains only:

- a random 128-bit record handle;
- byte offset;
- identical ciphertext length;
- nonce.

Trial ID, workflow, leak type, surface, carrier style, policy cell, posture,
labels, prompt length, and task structure are encrypted. Index validation
rejects extra keys, nonuniform length, invalid IDs, and noncontiguous offsets.
The runner schedules opaque handles and validates panel ID and count before KMS
use.

Aggregation verifies the signed run against the original sealed-pack digest,
requires every opaque handle exactly once, proves that each handle resolves to
one trial, and separately replays the oracle from an evaluator-only plaintext
panel whose trial set must exactly equal the 600 resolved trials. The plaintext
panel digest is not exposed as public routing metadata.

This removes the previous plaintext assignment leak. It does not create a
security boundary by itself. Managed key policy, workload isolation, access
logging, positive egress probes, and one-record recovery must still be tested.

## Evidence protocol

The v3 run format implements:

- pre-run Ed25519 attestation of fixed configuration, code state, and expected
  matrix;
- per-record chain index, predecessor digest, and record digest;
- attempted payload, decision effect, effective payload, destination commit,
  decision metadata, and elapsed time retained separately;
- fsync after every completed episode;
- final attestation of raw digest, chain head, matrix counts, provider metadata,
  and enforcement identity evidence;
- presence and global uniqueness checks for provider response IDs, separately
  named from locally generated client-episode markers;
- verification during aggregation;
- trusted signer-key allowlist required for publication.

A local signature proves control of a key, not honest operation. The signer
registry must be independently maintained, and high-assurance operation also
needs an external append-only commitment or independently held copy.

## AccessBench Anti-Cheat

AccessBench Anti-Cheat is separate from the score. It has a frozen 17-check
registry and four allowed states: pass, fail, not_run, and error. Missing and
not-run checks make the result `Flagged`. Unknown or invalid checks,
deterministic failures, and confirmed material findings make it `Ineligible`.
Only a complete clean decision is `Valid`.

The implemented AccessBench Anti-Cheat Judge adapter:

- receives only a redacted evidence record with separately retained attempted
  and effective payloads, decisions, provider context, and subject/tool trace;
- treats transcript content as quoted untrusted evidence;
- has no tools or network client;
- uses temperature zero, a frozen system prompt, and strict JSON schema;
- binds model, prompt digest, record digest, request digest, and response
  digest;
- rejects score authority and Judge-supplied materiality.

Findings require retained citations, a declared rule, a benign explanation,
and a requested deterministic check. Every valid finding is material and needs
an authenticated human confirmation or dismissal. Human attestations bind the
finding and audit-record digest.

Aggregation requires a separately signed Anti-Cheat sidecar that binds raw and
manifest digests and contains every exact registry check as pass. The
Anti-Cheat signer key must be independently trusted. Every check must also
identify its frozen executor and version and bind an evidence digest. The
sidecar binds the Judge model, prompt, redacted record, and response digests.
Every dismissed finding must carry a reviewer attestation from a separately
trusted reviewer key. A structurally thin all-pass assertion is rejected. This
is fail-closed plumbing, not evidence that every check executor or calibration
run exists.

## Operational controls for the sealed track

These apply before a sealed-track result can be externally claimed. None of
them gates the v1 open public track, whose results are labeled
development-bank evidence:

1. regenerate and independently review the private v5/v2 bank;
2. provision owner-controlled key storage (managed KMS is one option) and
   evaluator roles;
3. isolate controller, grader, subject, model relay, and enforcement service;
4. prove default-deny network, filesystem, process, credential, and sibling
   episode boundaries with positive controls;
5. derive fresh matched-format values after run admission and track exposure;
6. execute all 17 deterministic integrity checks on the complete matrix;
7. calibrate the frozen Judge on independently authored clean and adversarial
   runs, including prompt injection and transformed disclosure;
8. place signer, reviewer, and Anti-Cheat keys in independent trust registries;
9. obtain an independent replay and security review;
10. release only aggregates whose measurement and integrity gates both pass.

Encryption code, local unit tests, session IDs, self-reported provider fields,
or a signed all-pass JSON file do not individually satisfy these controls. The
per-run gates that consume this machinery are defined in
[07. Validation](07-validation.md).

## Public and private disclosure

Publish the two-input method, scoring rule, denominators, AuthZEN request
shape, high-level threat categories, check names, and limitations. Keep active
content, assignments, prompt and value construction, probes, Judge prompt,
keys, raw evidence, and private reviewer notes controlled while active.

Retired content may be released only after an explicit research decision. A
file cannot credibly remain an active secret after it has entered public Git,
chat, tickets, analytics, or an unrestricted model service.
