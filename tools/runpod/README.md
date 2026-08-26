# Self-hosted sweep on one GPU box

Everything here serves open-weight models on one 80 to 94 GB card and drives
`environment_lab/eval/run_eval.py` against them, one model at a time. Nothing
in this folder calls a hosted API.

| File | Job |
| --- | --- |
| `models.sh` | the roster: one pinned `vllm serve` line per key; sourced by the other scripts |
| `bootstrap.sh` | install vLLM and the download tooling, pre-download the roster, fetch the Llama tool template; starts nothing |
| `serve.sh KEY` | serve one model on `:8000` |
| `preflight_model.py` | prove that the exact adapter, template and parser produce a valid protocol tool call |
| `sweep.sh KEY...` | for each key: serve, preflight, run the paired benchmark, aggregate, stop the server |

## Pinned roster for the H100 trial track

The trial environment verified on 2026-08-21 is one H100 NVL, driver 580,
CUDA 13 and vLLM 0.27.1. `models.sh` pins the full Hugging Face snapshot hash
for every full-run local trial candidate.

| Key | Model | Loading | Trial status |
| --- | --- | --- | --- |
| `qwen32` | Qwen/Qwen3-32B | FP8 | full-run candidate after preflight |
| `mistral24` | mistralai/Mistral-Small-3.2-24B-Instruct-2506 | bfloat16 | full-run candidate after preflight; Mistral tokenizer mode |
| `qwencoder30` | Qwen/Qwen3-Coder-30B-A3B-Instruct | bfloat16 | full-run replacement for DeepSeek-Coder-Lite |
| `gptoss` | openai/gpt-oss-120b | MXFP4 | refusal-control candidate after preflight |
| `llama70` | meta-llama/Llama-3.3-70B-Instruct | FP8 | gated on Meta approval and preflight |
| `dscoder` | deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct | unverified | diagnostic only; excluded because its template did not render protocol tools |

`qwencoder` and `mistral4` remain disabled placeholders until their exact
weight revisions and serving configurations are separately admitted.

## Run order

On the box, once:

```bash
# 1. code and harness
git clone https://github.com/accessbench/accessbench.git /workspace/accessbench
cd /workspace/accessbench/environment_lab
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[hosted-api]" && deactivate
.venv/bin/python -m accessbench_env generate-signing-key --out ~/.accessbench/signing.key

# 2. vLLM 0.27.1 and exact weight snapshots
. /workspace/venv/bin/activate
HF_HOME=/workspace/hf bash ../tools/runpod/bootstrap.sh --check     # what is cached
HF_HOME=/workspace/hf bash ../tools/runpod/bootstrap.sh             # download the rest (long)
deactivate
```

Then the sweep, in a `tmux` session so an SSH drop does not kill it:

```bash
cd /workspace/accessbench
HF_HOME=/workspace/hf VLLM_ACTIVATE=/workspace/venv/bin/activate \
  bash tools/runpod/sweep.sh qwen32 mistral24 qwencoder30 gptoss llama70
tail -f environment_lab/results_raw/sweep_status.txt
```

Run the pinned 50-case local pilot before the full sweep with:

```bash
SMOKE_TRIALS=50 HF_HOME=/workspace/hf \
  VLLM_ACTIVATE=/workspace/venv/bin/activate \
  bash tools/runpod/sweep.sh qwen32
```

Smoke output is diagnostic and never publication eligible. Omit
`SMOKE_TRIALS` for the fixed 600-case run.

The sweep refuses a pinned trial run unless it can bind a clean Git commit,
exact weight revision, quantization mode, vLLM version, serving-command hash,
orchestrator hash and successful preflight hash. If code was copied without
`.git`, export `ACCESSBENCH_HARNESS_GIT_COMMIT` to the deployed tag commit and
`ACCESSBENCH_HARNESS_GIT_DIRTY=no`.

`DRY_RUN=1` prints the plan and touches nothing. `ENFORCEMENT=` swaps the
gate. A failed model is logged and skipped; the next one still runs. Results
land in `results/<stamp>-vllm-<model>/summary.json` like any other run, and
`results_raw/logs/` holds the serve, run and aggregate logs per key.

## Budget

One paired run is 1,200 episodes, about 2.7 M prompt tokens and 0.13 M
completion tokens on gpt-4o; local models see a similar volume. On one H100
expect roughly 30 to 60 minutes per model including load, so five models is
an afternoon, around four hours of pod time. Weights for the five are about
250 GB; keep them on the persistent volume so the next rental does not
re-download.

## Hosted fallback

The same runner takes any OpenAI-compatible endpoint. For Gemini:

```bash
export ACCESSBENCH_MODEL_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
export OPENAI_API_KEY=$GEMINI_API_KEY
export ACCESSBENCH_SPEND_APPROVED=yes     # hosted endpoints trip the spend guard on purpose
python eval/run_eval.py --model gemini-3.5-flash --enforcement benchmark_pdp_v3
```

Check the live price in the Google console first; at the mid-2026 list price a
paired run is roughly five dollars on the flash tier. Smoke it with
`ACCESSBENCH_SMOKE_TRIALS=12` before the full bank.
