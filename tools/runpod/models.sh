#!/usr/bin/env bash
# Single source of truth for the AccessBench local roster (80 GB tier).
# Sourced by bootstrap.sh (download) and serve.sh (launch). Requires bash 4+.
#
# Every full-run trial candidate is pinned to an exact Hugging Face snapshot.
# A model still has to pass preflight_model.py under the deployed vLLM build
# before a full run. DeepSeek-Coder-V2-Lite remains as a diagnostic-only
# incompatibility record and is deliberately absent from every full-run order.

if [[ -z "${BASH_VERSINFO:-}" || "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "models.sh needs bash 4+ (associative arrays). Stock macOS bash is 3.2." >&2
  echo "This is fine: run these ON the Linux GPU box (bash 5), not your Mac." >&2
  echo "To try locally: 'brew install bash' then run with /opt/homebrew/bin/bash." >&2
  return 1 2>/dev/null || exit 1
fi

declare -A REPO SERVE TIER REVISION QUANT TRIAL_ENABLED DOWNLOAD_EXCLUDE

# --- Family A: Qwen (Apache-2.0) ------------------------------------------
REPO[qwen32]="Qwen/Qwen3-32B"
TIER[qwen32]="80gb"
REVISION[qwen32]="9216db5781bf21249d130ec9da846c4624c16137"
QUANT[qwen32]="fp8"
TRIAL_ENABLED[qwen32]="yes"
SERVE[qwen32]="vllm serve Qwen/Qwen3-32B --port 8000 --quantization fp8 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len 32768 --gpu-memory-utilization 0.90"

REPO[qwencoder]="Qwen/Qwen3-Coder-Next"                       # CONFIRM id
TIER[qwencoder]="80gb"
REVISION[qwencoder]=""
QUANT[qwencoder]="awq-unverified"
TRIAL_ENABLED[qwencoder]="no"
SERVE[qwencoder]="vllm serve Qwen/Qwen3-Coder-Next --port 8000 --quantization awq \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len 65536 --gpu-memory-utilization 0.92 --trust-remote-code"  # CONFIRM parser

# --- Family B: Mistral (Apache-2.0) ---------------------------------------
REPO[mistral24]="mistralai/Mistral-Small-3.2-24B-Instruct-2506"
TIER[mistral24]="80gb"
REVISION[mistral24]="95a6d26c4bfb886c58daf9d3f7332c857cb27b43"
QUANT[mistral24]="bfloat16"
TRIAL_ENABLED[mistral24]="yes"
SERVE[mistral24]="vllm serve mistralai/Mistral-Small-3.2-24B-Instruct-2506 --port 8000 \
  --tokenizer-mode mistral --config-format mistral --load-format mistral \
  --dtype bfloat16 \
  --enable-auto-tool-choice --tool-call-parser mistral \
  --max-model-len 32768 --gpu-memory-utilization 0.90"   # tokenizer-mode mistral is required

REPO[mistral4]="mistralai/Mistral-Small-4-119B-2603"          # CONFIRM id
TIER[mistral4]="80gb"
REVISION[mistral4]=""
QUANT[mistral4]="awq-unverified"
TRIAL_ENABLED[mistral4]="no"
SERVE[mistral4]="vllm serve mistralai/Mistral-Small-4-119B-2603 --port 8000 --quantization awq \
  --enable-auto-tool-choice --tool-call-parser mistral \
  --max-model-len 32768 --gpu-memory-utilization 0.95"        # CONFIRM parser+quant

# --- Family C: DeepSeek ----------------------------------------------------
REPO[dscoder]="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
TIER[dscoder]="80gb"
REVISION[dscoder]="e434a23f91ba5b4923cf6c9d9a238eb4a08e3a11"
QUANT[dscoder]="unverified"
TRIAL_ENABLED[dscoder]="no"
SERVE[dscoder]="vllm serve deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct --port 8000 \
  --enable-auto-tool-choice --tool-call-parser deepseek_v3 \
  --max-model-len 32768 --trust-remote-code"                  # CONFIRM parser

REPO[dsflash]="deepseek-ai/DeepSeek-V4-Flash"                 # CONFIRM id
TIER[dsflash]="burst-2gpu"
REVISION[dsflash]=""
QUANT[dsflash]="awq-unverified"
TRIAL_ENABLED[dsflash]="no"
SERVE[dsflash]="vllm serve deepseek-ai/DeepSeek-V4-Flash --port 8000 --quantization awq \
  --tensor-parallel-size 2 --enable-auto-tool-choice --tool-call-parser deepseek_v3 \
  --max-model-len 131072 --trust-remote-code"                 # BURST: needs 2x80 GB

# --- Family D: Meta Llama (community licence) ------------------------------
# Online fp8 quantisation at load; ~70 GB of VRAM after load, fits one 80/94 GB card.
# The llama3_json parser needs the tool chat template, which the pip wheel does
# not ship: download it once into $HF_HOME (bootstrap.sh does this).
REPO[llama70]="meta-llama/Llama-3.3-70B-Instruct"            # gated: accept licence on HF first
TIER[llama70]="80gb"
REVISION[llama70]="6f6073b423013f6a7d4d9f39144961bfbfbc386b"
QUANT[llama70]="fp8"
TRIAL_ENABLED[llama70]="yes"
DOWNLOAD_EXCLUDE[llama70]="original/*"
SERVE[llama70]="vllm serve meta-llama/Llama-3.3-70B-Instruct --port 8000 --quantization fp8 \
  --enable-auto-tool-choice --tool-call-parser llama3_json \
  --chat-template \${HF_HOME:-/workspace/hf}/tool_chat_template_llama3.1_json.jinja \
  --max-model-len 32768 --gpu-memory-utilization 0.92"

# Alternate if llama70 is too slow to download: same Qwen family, MoE, fast.
REPO[qwencoder30]="Qwen/Qwen3-Coder-30B-A3B-Instruct"
TIER[qwencoder30]="80gb"
REVISION[qwencoder30]="b2cff646eb4bb1d68355c01b18ae02e7cf42d120"
QUANT[qwencoder30]="bfloat16"
TRIAL_ENABLED[qwencoder30]="yes"
SERVE[qwencoder30]="vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --port 8000 \
  --dtype bfloat16 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --max-model-len 32768 --gpu-memory-utilization 0.90"

# --- Control: gpt-oss (high-refusal contrast) ------------------------------
REPO[gptoss]="openai/gpt-oss-120b"
TIER[gptoss]="80gb"
REVISION[gptoss]="b5c939de8f754692c1647ca79fbf85e8c1e70f8a"
QUANT[gptoss]="mxfp4"
TRIAL_ENABLED[gptoss]="yes"
DOWNLOAD_EXCLUDE[gptoss]="original/* metal/*"
SERVE[gptoss]="vllm serve openai/gpt-oss-120b --port 8000 \
  --enable-auto-tool-choice --tool-call-parser openai \
  --max-model-len 32768 --gpu-memory-utilization 0.90"

# Order for the 80 GB weight-swap sweep (dsflash excluded; it is the burst).
# qwencoder and mistral4 remain disabled until their snapshots are verified.
# dscoder was removed after its template rendered no tool schemas in 471/600
# cases per arm. Qwen3-Coder-30B is its already-cached trial replacement.
ORDER_80GB=(qwen32 mistral24 qwencoder30 gptoss llama70)
ORDER_CUDA13_EXTRA=(qwencoder mistral4)
