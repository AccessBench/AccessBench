# 04. Setup: install and first run

Status: private internal. Current version: see VERSION.

This gets you from a fresh clone to a verified result directory. Read it top
to bottom the first time; every step is copy-paste. Finish the offline path
before touching a model. Background on what you are running is in
[01-design.md](01-design.md); the enforcement contract details are in
[06-integrity.md](06-integrity.md) and [10-replication.md](10-replication.md).

| Path | What you get | Needs | Cost |
| --- | --- | --- | --- |
| 1. Offline, zero cost | Grader proof, test suite green, enforcement seam proven, a verified demo bundle | Python 3.11+ | $0 |
| 2. Model-only users | The paired experiment for a hosted or self-hosted model behind the reference decision point | a model endpoint; API key and spend approval if hosted | per provider or GPU rental |
| 3. PDP implementers | The same experiment with your own enforcement endpoint as the second arm | a model endpoint plus an AuthZEN HTTP(S) endpoint | same |

All benchmark work happens inside `environment_lab/`.

![The offline path proves the grader with no model attached; the hosted and self-hosted paths both reach the same run interface, whose raw events are aggregated into a summary the dashboard reads](assets/fig-setup.svg)

## Install

- macOS or Linux (Windows under WSL2).
- Python 3.11 or newer: check with `python3 --version`.
- git.

```bash
git clone https://github.com/accessbench/accessbench.git
cd accessbench/environment_lab
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[hosted-api]"
```

This installs the `accessbench` console script (`accessbench-env` is the same
command under its older name). The `hosted-api` extra adds the
OpenAI-compatible client; any live model run, hosted or self-hosted, needs it.
Every new shell afterwards:

```bash
cd accessbench/environment_lab && . .venv/bin/activate
```

## Path 1. Offline, zero cost: demo and verify

### 1.1 The grader proof

```bash
accessbench demo
```

This replays six core-panel cases through their reference plan, printing
exact-match, copy-tracking, task-success and refusal results. It reads the
tracked `catalog/core_v2.jsonl` and writes nothing. It finishes in under a
minute on a clean machine, needs no key and costs nothing. It prints that it is a grader proof,
not a benchmark result. `accessbench run` with no flags does the same thing.

### 1.2 The test suite

```bash
python -m accessbench_env generate --split public --out catalog/public.jsonl
python -m unittest discover -s tests     # needs nothing beyond the install and the line above
python -m pytest tests                   # what CI runs; pip install -e ".[dev]" first
```

`catalog/public.jsonl` is gitignored, not tracked, so a fresh clone does not
have it; the generate step above builds it locally (same command CI runs
before testing). Skipping it fails a batch of tests in
`tests/test_eval_pipeline.py` with `FileNotFoundError` on that path, not a
real bug. The whole suite is otherwise offline and needs no key or GPU. Two
tests in
`tests/test_prerun_acceptance_evidence_runpod.py` drive the GPU-box shell
scripts and need Bash 4 or newer; on macOS, where `/bin/bash` is 3.2, they
skip and say why (install a newer bash and set `ACCESSBENCH_TEST_BASH` to its
path to run them). Continuous integration runs them on Linux. Anything else
that fails on a clean checkout: stop and raise it before going further.

### 1.3 Prove the wiring and the bring-your-own-PDP seam

```bash
python eval/verify_pipeline.py
python eval/demo_http_enforcer.py
```

The first drives a scripted stub agent through the live runner against
built-in enforcement layers and shows the enforcement input changing the
grader outcome: the whole experiment in miniature, with no inference spend.
The second starts a mock policy decision point on localhost, points the
harness at it over HTTP, and shows an external decision changing the outcome.
That HTTP seam is where an external enforcement input plugs in.

### 1.4 The evidence-signing key

Every run signs its manifest and evidence chain, so the runner refuses to
start without a key. `accessbench run` provisions one on first use at
`~/.accessbench/signing-key.pem` if `ACCESSBENCH_SIGNING_KEY` is not set and
`--signing-key PATH` is not given. To keep the key somewhere specific instead:

```bash
accessbench generate-signing-key --out ~/.accessbench/signing.key
export ACCESSBENCH_SIGNING_KEY=~/.accessbench/signing.key
```

Keep the key outside `results_raw/` and never commit it. The key is yours: a
result signed with it proves the bundle was not altered after the run and is
internally consistent. It does not prove anything about the operator, and it
is not independent validation.

`TRUSTED_KEYS.json` at the repository root lists the signing keys the
maintainers have admitted (`accessbench trust list` prints them). A key you
provisioned yourself is not in it, so `accessbench run --full` prints that
your key is not in the trusted-key registry and that the result will not be
publication-eligible. That message is expected for every self-signed run and
changes nothing about the scores. What the registry does and does not prove
is in [10-replication.md](10-replication.md).

Path 1 done. You now know the harness works on your machine.

## Path 2. Model-only users (hosted or self-hosted endpoint)

You have a model endpoint and want its behavior behind the reference decision
point. The runner takes two benchmark inputs, `--model` and `--enforcement`;
transport comes from the environment.

### 2.1 Configure the endpoint

```bash
export ACCESSBENCH_MODEL_BASE_URL=https://api.openai.com/v1   # default http://localhost:8000/v1
export OPENAI_API_KEY=sk-...
export ACCESSBENCH_SPEND_APPROVED=yes
```

Never commit the key and never paste it into a shared channel. The spend
guard is deliberate: a base URL that is not a local or private address refuses
to run unless `ACCESSBENCH_SPEND_APPROVED=yes` is set for that invocation, so
nobody starts a paid run by accident. Local and private-network endpoints
(a vLLM server, for example) need no key and no approval.
`ACCESSBENCH_MODEL_API_MODE` defaults to `auto` and picks the right API shape
for the endpoint.

### 2.2 The preflight

One preflight runs before any inference, in this order:

1. signing key: present, or provisioned;
2. credentials: a non-local `ACCESSBENCH_MODEL_BASE_URL` requires
   `OPENAI_API_KEY` and `ACCESSBENCH_SPEND_APPROVED=yes`;
3. disk: 2 GB free;
4. PDP conformance, for URL enforcements only;
5. model tool-use check: one tiny tool-call request.

`--skip-model-preflight` skips check 5 only; the other four always run. Use it
when the same endpoint and model already passed it (a rerun or a resume).

Before a hosted run it prints the episode count and the measured token volume
of a full paired run (about 2.7M prompt and 0.13M completion tokens per 1,200
episodes on gpt-4o-class models). It prints a dollar estimate only if
`ACCESSBENCH_PRICE_PER_M_INPUT` and `ACCESSBENCH_PRICE_PER_M_OUTPUT` are set.
Cost depends entirely on the model, so read the estimate and the smoke run
before committing to the full bank.

### 2.3 Smoke first

```bash
accessbench run --model gpt-4o-mini --enforcement benchmark
```

Without `--full` this is a smoke sample of a handful of cases (six by
default; `ACCESSBENCH_SMOKE_TRIALS=N`, 1 to 600, changes the sample size). It
prints "SMOKE SAMPLE, NOT A REPORTABLE RESULT" and its evidence is permanently
marked as such; it can never become a headline number at any size. It exists
to prove wiring and measure cost.

### 2.4 The full run

```bash
accessbench run --model gpt-4o-mini --enforcement benchmark --full
```

`--full` is the 600-case, two-arm, one-pass-per-arm protocol: 1,200 episodes.
The no-enforcement arm runs automatically; `--enforcement` names the second
arm. `benchmark` is the public name for the Benchmark PDP, the reference
decision point, resolved to the built-in id `benchmark_pdp_v3` and recorded as
such in the evidence. Any other built-in id (`benchmark_pdp` and
`benchmark_pdp_v2` are earlier revisions, kept so older runs stay comparable)
or an AuthZEN HTTP(S) URL also works. A full run also runs the Anti-Cheat
Judge and writes the signed integrity sidecar; `--judge-model M` and
`--judge-sample-target N` adjust it. Before the episodes start, `--full`
calibrates that Judge model on a fixed fixture set (live judge calls, not
counted in the spend estimate above; cached under `~/.accessbench/calibration`)
and stops if its precision is below 0.90; `--recalibrate` forces a fresh
calibration. For a long run use `tmux` or `nohup` so a closed laptop lid does
not kill it.

### 2.5 Verify

```bash
accessbench verify ../results/<stamp>-<provider>-<model>   # run prints the exact path
```

One command checks the bundle shape, the raw digest against the manifest,
completeness (and says whether the run was smoke or full), the per-record hash
chain against the manifest head, the pre-run and result signatures against the
key embedded in the manifest, recomputes the scores from the raw and compares
them to `summary.json`, and checks the integrity sidecar if present. It prints
PASS or FAIL per check and the numbers of record, and exits 0 only if every
check passes. `--json` gives machine-readable output.

### 2.6 Resume

The runner checkpoints every episode as it completes. After repeated transport
failures (a dead network, a revoked key, a billing stop) it aborts cleanly
rather than writing junk, and prints the exact resume command:

```bash
accessbench run --model gpt-4o-mini --enforcement benchmark --full --resume <RAW>
```

Resume refuses to continue under a changed configuration and never re-runs an
episode that is already retained. `--skip-model-preflight` skips the model
tool-use check on a rerun.

## Path 3. PDP implementers

You have an enforcement endpoint. Check its contract first:

```bash
accessbench conformance --enforcement https://your-pdp/...
```

It sends only synthetic event views, never scored-bank content, and reports
pass or fail per check. If the endpoint needs authentication, set
`ACCESSBENCH_ENFORCEMENT_BEARER_TOKEN`. Then run and verify as in Path 2, with
your URL as the enforcement input:

```bash
accessbench run --model MODEL --enforcement https://your-pdp/... --full
accessbench verify ../results/<stamp>-<provider>-<model>   # run prints the exact path
```

`run` repeats the conformance check in its preflight. The AuthZEN contract,
what the endpoint sees and what it never sees, is in
[06-integrity.md](06-integrity.md).

## Where results land

Each run ends in one self-contained directory at the repository root:

```text
results/<stamp>-<provider>-<model>/
  summary.json      the scored result
  report.html       readable report, percent first, vertical paired bars
  run.json          the exact configuration
  evidence/         the signed raw .jsonl, its .manifest.json, and the
                    .integrity.json sidecar when --full ran the Anti-Cheat Judge
  VERIFY.txt        the verify command and digests
```

The raw evidence also still appears under `environment_lab/results_raw/`, one
signed, hash-chained record per episode plus the manifest that freezes the
model, enforcement, catalog digest, protocol settings and code state before
inference begins. The low-level pieces `run` calls into are unchanged:
`python eval/run_eval.py --model MODEL --enforcement ENFORCEMENT` is the
runner and `python eval/aggregate.py` the scorer, and `accessbench verify
--raw PATH` verifies an older results directory whose raw still lives only in
`results_raw/`. The optional local viewer is `python3 dashboard/server.py`
from the repository root (binds to 127.0.0.1; `ACCESSBENCH_DASHBOARD_PORT`
changes the port). It is not required.

## Self-hosted serving kit

For models not behind a hosted API, serve an OpenAI-compatible endpoint and
point the runner at it; nothing about the harness changes. The serving kit is
`tools/runpod/`: `bootstrap.sh` installs vLLM on the GPU box and pre-downloads
the roster, `models.sh` is the pinned roster, `serve.sh <key>` serves one
model on port 8000, and `sweep.sh <key> ...` runs the roster unattended.
`tools/runpod/README.md` has the run order. `model_agent.py` and
`run_sweep.py` there are older reference scripts and are not the runner.
Prefer running the harness on the same box as the server; a public proxy URL
works but is slower and trips the spend guard.

## Common problems

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: openai` or `cryptography` | You are outside the venv, or skipped the install. Activate `.venv` and `pip install -e ".[hosted-api]"` |
| runner error about `ACCESSBENCH_SIGNING_KEY` | Do step 1.4 and export the variable in this shell, or let `accessbench run` provision one |
| runner error about spending money on a hosted endpoint | The base URL is non-local. Set `ACCESSBENCH_SPEND_APPROVED=yes` only for an approved run |
| preflight fails | Fix the named check; the preflight prints the exact command to run next |
| `generated output collision; run again` | Two runs started in the same instant; just rerun |
| resume refused: different configuration | Model, enforcement, catalog, or protocol changed since the interrupted run. Start fresh or restore the original settings |
| `accessbench verify` prints FAIL | Do not report the bundle. A digest or signature mismatch means the evidence was edited or the pair is corrupt |
| run dies midway | Rerun with the printed `--resume` command |

## What not to do

- Do not present a smoke run as a result. Only the complete 600-case bank
  counts, and the manifest records which one you ran.
- Do not call a self-signed run independently validated. `verify` proves the
  bundle is intact and internally consistent, nothing more.
- Do not sample the bank, change the case set, or alter protocol settings.
- Do not put a real API key in any committed file.
- Do not make this repository public.
