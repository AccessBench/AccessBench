# 11. Results: seven models, one gate

Updated 2026-08-22. Harness commit `2040bcf` (tag v0.16.5), enforcement
`benchmark_pdp_v3`, panel `accessbench-core-v2-development-600`. Development
bank by design: every run below carries `publication_eligible: false`. These
are pre-release engineering measurements that show the protocol working across
model families; every bundle is self-signed by the operator who ran it; they
are not held-out, preregistered, or independently validated, and they are not
a publishable model claim.

![Two rows of paired bars, one pair per model. Protected data exfiltrated falls from 37 to 39 percent of all cases with no enforcement to 1.5 percent behind the Benchmark PDP for every model. Work completed safely rises from 33 to 60 percent to 56 to 92 percent, and the spread between models is on that second row](assets/fig-models.svg)

## The one-sentence reading

Across seven models, from a 24B open-weight model to a hosted reasoning model,
unenforced exfiltration sits in a two-point band (37.3 to 39.3 percent of all
600 cases); behind the Benchmark PDP it collapses to the same 9 cases (1.5
percent) for six of the seven and 10 for the seventh; and what the gate cannot
give back, work completed safely, ranges from 55.5 to 91.5 percent and is the
model's doing.

## Numbers of record (primary pass per model)

Percent first, counts as subtext. "Safe" is work completed with no
exfiltration. "Exfil" is protected data exfiltrated, out of all 600 cases;
allowed cases cannot leak by construction, so the ceiling is 300.

| Model | Serving | Safe, no enforcement | Exfil, no enforcement | Safe, behind PDP | Exfil, behind PDP | Refusal none / PDP | Task done none / PDP |
|---|---|---|---|---|---|---|---|
| gpt-4o (`gpt-4o-2024-08-06`) | hosted, Responses | 58.2% (349/600) | 37.7% (226/600) | 85.8% (515/600) | 1.5% (9/600) | 2.3 / 2.7% | 92.2 / 87.3% |
| gpt-5.6 Sol | hosted, Responses, provider-default reasoning | 60.2% (361/600) | 38.2% (229/600) | 91.5% (549/600) | 1.5% (9/600) | 0.0 / 3.2% | 97.8 / 93.0% |
| Llama 3.3 70B Instruct | vLLM 0.27.1, fp8 | 54.8% (329/600) | 37.3% (224/600) | 81.8% (491/600) | 1.5% (9/600) | 0.0 / 2.2% | 86.7 / 83.3% |
| Mistral Small 3.2 24B Instruct 2506 | vLLM 0.27.1, bf16 | 32.8% (197/600) | 38.7% (232/600) | 55.5% (333/600) | 1.7% (10/600) | 0.5 / 2.7% | 53.8 / 56.3% |
| gpt-oss-120b (control) | vLLM 0.27.1, mxfp4 | 56.8% (341/600) | 37.7% (226/600) | 86.2% (517/600) | 1.5% (9/600) | 0.3 / 3.2% | 91.2 / 87.7% |
| Qwen3-32B | vLLM 0.27.1, fp8 | 58.0% (348/600) | 38.2% (229/600) | 86.8% (521/600) | 1.5% (9/600) | 0.0 / 1.8% | 93.0 / 88.3% |
| Qwen3-Coder-30B-A3B Instruct | vLLM 0.27.1, bf16 | 38.5% (231/600) | 39.3% (236/600) | 64.2% (385/600) | 1.5% (9/600) | 4.2 / 7.7% | 64.7 / 65.2% |

Arm labels everywhere: **foundation model behavior, no enforcement** and
**behind the Benchmark PDP**. Nothing here ranks or evaluates a security
vendor's product; the Benchmark PDP is a reference decision point.

## Fixed protocol

600 cases, one pass per arm, 8 turns, max 700 tokens per turn, concurrency 16,
one tool call per assistant turn, `parallel_tool_calls=false` on every request.
Open-weight models run on one H100 NVL (94 GB) with pinned Hugging Face
snapshot revisions and a per-request seed; temperature 0 where the endpoint
accepts it. The hosted Responses endpoint exposes no seed; gpt-5.6 Sol also
receives no temperature and no reasoning-effort override (provider default,
documented as medium). The paired within-model comparison is valid for every
row; no decoding equivalence between hosted and local subjects is claimed.

## Replication passes and the trial rule

Every model was run more than once on the same commit. The trial rule, fixed
before the runs, is: identity, overlap and sample checks clean, and a
case-level flip rate of 2 percent or less on a 120-case stratified subset
(60 allowed, 60 forbidden, all 25 leak types, seed 20260821). Verdicts are
reported beside the development-bank fact, not instead of it.

| Model | Passes | Flip rate, any outcome | Leak flips (behind PDP / no enforcement) | Verdict under the rule as written |
|---|---|---|---|---|
| gpt-4o | 3 | 4.2% | 0 / 0 | flip rate above 2% |
| gpt-5.6 Sol | 3 | 0.8% | 0 / 0 | within rule |
| Llama 3.3 70B | 3 | 7.5% | 0 / 0 | flip rate above 2% |
| Mistral Small 3.2 24B | 3 | 20.8% | 0 / 1 | flip rate above 2% |
| gpt-oss-120b | 3 | 10.0% | 0 / 1 | flip rate above 2% |
| Qwen3-32B | 3 | 0.8% | 0 / 0 | within rule |
| Qwen3-Coder-30B-A3B | 2 accepted | 4.2% | 0 / 1 | flip rate above 2% |

Behind the Benchmark PDP, exfiltration is identical in every pass of every
model (the same 9 cases, 3.3% of the 120-case subset, standard deviation 0):
no case leaked behind the gate in one pass and held in another. In the
no-enforcement arm, one subset case flipped between leaking and not leaking
across passes for three models (Mistral, gpt-oss-120b, Qwen3-Coder); every
other flip is a task-completion flip. Six models have three passes; Qwen3-Coder
has two accepted passes because one completed pass was refused by the
aggregate on an evidence check (a client-side exception before any provider
response) and is excluded, not repaired.

## The shared 9 cases

Behind the Benchmark PDP, 9 case ids leak in every model (a tenth in Mistral
only): overfetch, join dereference, field security and retrieval bleed cases
at the model-context boundary. They are a property of the reference decision
point and the bank's labels (an enforcement observability gap), not of any
model's run, and the gate is not tuned to them. [08. Limits](08-limits.md)
carries the accounting.

## Where the evidence is

Each run produces a signed raw record file, a manifest bound to the commit,
weight revision, serving configuration and preflight digest, and a
`results/<stamp>-<provider>-<model>/summary.json`. Raw evidence is retained by
the maintainer and is reproducible from [10. Replication](10-replication.md).
