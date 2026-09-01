<div align="center">

**AccessBench**

Benchmark for Agent AI Governance in measuring data overreach.

[ [Read the docs](docs/01-design.md) ]

Python 3.11+ | Apache 2.0 | Version: see VERSION

<img src="docs/assets/hero.svg" width="520" alt="An agent walks through an open app door and reaches every record behind it, field by field, with nothing checking which ones it was allowed to see">

</div>

---

AccessBench measures one question: when an AI agent does ordinary business
work, does the enforcement layer allow the useful flow and stop the data
exfiltration? It takes two inputs, a model endpoint and an enforcement
endpoint, runs the same 600 fixed cases once with no enforcement and once
behind the enforcement layer under test, and writes one signed result
directory. It is an open research preview: the evidence so far is reproducible
development-bank evidence, self-signed by the operator who ran it, and not an
independently validated claim about any model or product.

![Two inputs, a model endpoint and an enforcement endpoint, enter the harness; the same 600 fixed cases run once with no enforcement and once with the enforcement layer under test; one signed results file comes out](docs/assets/fig-run.svg)

## Install

```bash
git clone https://github.com/accessbench/accessbench.git
cd accessbench/environment_lab
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[hosted-api]"
```

This installs the `accessbench` command (`accessbench-env` is the same
command under its older name).

## Quick start

```bash
# 1. offline grader proof, no key, no cost, under ten minutes: not a benchmark result
accessbench demo

# 2. smoke sample of your model behind the reference decision point: wiring and cost only
accessbench run --model MODEL --enforcement benchmark

# 3. the full 600-case, two-arm protocol (1,200 episodes): the only thing that is a result
accessbench run --model MODEL --enforcement benchmark --full

# 4. the same run with your own enforcement endpoint (AuthZEN over HTTPS)
accessbench run --model MODEL --enforcement https://your-pdp/... --full

# 5. check any result directory: digests, signatures, recomputed scores (run prints the exact path)
accessbench verify ../results/<dir>
```

> [!NOTE]
> A run without `--full` is a smoke sample. It prints "SMOKE SAMPLE, NOT A
> REPORTABLE RESULT" and is never a result. A full run is 600 cases, two arms,
> one pass per arm, 1,200 episodes, with one preflight before any inference.

`accessbench run` with no flags is the same offline proof as `accessbench demo`.
`--enforcement benchmark` is the public name for the Benchmark PDP, the
reference decision point that runs when nobody plugs in their own; it is
recorded in the evidence under its built-in id, `benchmark_pdp_v3`.

### Two ways in

- **You have a model endpoint** and want to know how it behaves behind the
  reference decision point: `accessbench demo`, then `accessbench run --model
  MODEL --enforcement benchmark` (smoke, then `--full`), then `accessbench
  verify`.
- **You have an enforcement endpoint** (a policy decision point): check it
  with `accessbench conformance --enforcement <URL>`, run with
  `--enforcement <URL>`, then `accessbench verify`. The endpoint sees only the
  event view, never the answer key.

Hosted-model prompts and synthetic tool data go to the model endpoint you
select. AccessBench itself sends no telemetry and uploads no results; a local
vLLM run stays fully local.

What `run` does step by step, the preflight, the spend guard, and where the
result directory lands are in [04. Setup](docs/04-setup.md). The low-level
pieces it calls into are `python eval/run_eval.py` and `python eval/aggregate.py`.

## Documentation

The eleven documents in `docs/` are the complete reference, numbered in
reading order:

- [01. Design](docs/01-design.md): how one case runs end to end.
- [02. Methodology](docs/02-methodology.md): why it is built this way, why it
  matters, and the AccessBricks case study on a real lakehouse.
- [03. Scope](docs/03-scope.md): what it measures and the 600-case contract.
- [04. Setup](docs/04-setup.md): install, first run, hosted and self-hosted
  models.
- [05. Leak types](docs/05-leak-types.md): the 25 leak types, named and
  defined.
- [06. Integrity](docs/06-integrity.md): asset boundary, threat model,
  Anti-Cheat.
- [07. Validation](docs/07-validation.md): the gates every result must pass.
- [08. Limits](docs/08-limits.md): what a result does and does not prove.
- [09. Dictionary](docs/09-dictionary.md): every term, with the data field it
  maps to.
- [10. Replication](docs/10-replication.md): reproduce every number, digest
  for digest.
- [11. Results](docs/11-results.md): seven models behind the same gate, the
  cross-model figure, replication passes, and the trial rule.

## Results and versions

Current version: see `VERSION` and `CHANGELOG.md`. The scored corpus is the
core-v2 development panel, 600 fixed cases
(`environment_lab/catalog/core_v2.jsonl`, panel
`accessbench-core-v2-development-600`). Development-bank results are internal
measurements only; publication-eligible results require the gates in
[07. Validation](docs/07-validation.md). 1.0.0 is the first public cut.

### What one run looks like

The same agent, the same 600 cases, the same grader. The only thing that
changes between the two bars of each pair is whether an enforcement layer sits
between the agent and the data. Grey is foundation model behavior, no
enforcement; scarlet is the agent behind the Benchmark PDP, the reference
decision point that runs when nobody plugs in their own.

![Two rows of paired bars, one pair per model. Protected data exfiltrated falls from 37 to 39 percent of all cases with no enforcement to 1.5 percent behind the Benchmark PDP for every model. Work completed safely rises from 33 to 60 percent to 56 to 92 percent, and the spread between models is on that second row](docs/assets/fig-models.svg)

Read it with the caveats attached. These are development-bank numbers: seven
models, from a 24B open-weight model to a hosted reasoning model, at harness
commit `2040bcf` behind Benchmark PDP v3, one pass per arm as the number of
record and two more passes as stability diagnostics. Every bundle is
self-signed by the operator who ran it, the integrity status of the panel is
Ineligible by design, nothing here is a publishable claim about any model or
any product, and nothing ranks a vendor. Without enforcement every model moved
protected data in 37.3 to 39.3 percent of all 600 cases. Behind the Benchmark
PDP that is the same 9 cases (1.5 percent) for six of the seven models and 10
for Mistral, identical in every pass, and the spread between models moves to
work completed safely, 55.5 to 91.5 percent. The numbers of record, the
replication passes and the accounting of those 9 cases are in
[11. Results](docs/11-results.md) and [08. Limits](docs/08-limits.md).

A newer development panel, core-v3 (636 cases, 26 leak mechanisms, four
prompt surfaces, three label-completeness regimes), ran six models on
2026-08-30 and 31: GPT-5.6 Sol, Gemini 3.1 Pro, Grok 4.6, GLM-5.2, Llama 3.3
70B and Mistral Small 3.2. Without enforcement 28.6 to 38.0 percent of all
cases exfiltrated; behind the Benchmark PDP 1.1 to 1.6 percent, the same seven
sparse-label cases in every model. That batch is summarized at
[accessbench.io](https://accessbench.io). It is single-pass evidence from an
unfrozen harness and is not yet part of this repository's results of record.

## Signing keys and what is not in use yet

Every result is signed by the key of the operator who ran it. This repository
ships no trusted-key registry: no `TRUSTED_KEYS.json`, no admitted keys. The
registry mechanism (`accessbench trust add-key` / `trust list`) stays in the
code for the day an outside party holds part of it; until then `accessbench
run --full` prints that your key is not in the registry, which is expected for
every run and changes nothing about the scores. The sealed evaluation bank and
its managed-KMS encryption (`sealed_assets.py`, the `kms-aws` extra) are also
a later track: no cloud account, key, or sealed pack exists, and nothing in
the current protocol uses AWS. See [08. Limits](docs/08-limits.md).

## Citation

Cite as: PJ Mullin and Jonas Tirona, "AccessBench: a fixed-bank benchmark for
AI-agent data-access enforcement," 2026. See `CITATION.cff` for the exact
release version and format.

## License

Code is Apache 2.0 (see `LICENSE` and `NOTICE`). The public 600-case
development bank ships under Apache 2.0 as well, same terms as the code, one
license for the whole repository.

Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
