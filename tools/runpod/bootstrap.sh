#!/usr/bin/env bash
# Run this ON the 80 GB GPU box to get everything ready to serve.
# It installs deps and downloads all 80 GB-tier weights + the gpt-oss control.
# It does NOT start any server and does NOT run the benchmark. That is deliberate
# PJ will give run instructions separately.
#
#   bash bootstrap.sh            # deps + download 80 GB-tier models (incl gpt-oss)
#   bash bootstrap.sh --flash    # also pre-download DeepSeek V4-Flash (big; burst)
#   bash bootstrap.sh --check    # verify what is already downloaded, no install
#
# Requires bash 4+, the CUDA 13/driver 580 environment used by vLLM 0.27.1,
# and about 300 GB free on the persistent volume.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/models.sh"

: "${HF_HOME:=/workspace/hf}"
export HF_HOME
mkdir -p "$HF_HOME"

WANT_FLASH=0; ONLY_CHECK=0
for a in "$@"; do
  [[ "$a" == "--flash" ]] && WANT_FLASH=1
  [[ "$a" == "--check" ]] && ONLY_CHECK=1
done

echo "== AccessBench box bootstrap =="
echo "HF_HOME=$HF_HOME"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null \
  || { echo "!! no nvidia-smi, is this a GPU box?"; }

if [[ "$ONLY_CHECK" == "0" ]]; then
  echo "-- installing vllm + hf cli + openai (this can take a few minutes)"
  pip install -q -U "vllm==0.27.1" "huggingface_hub[cli]" openai
fi
# `hf` is the current CLI name; `huggingface-cli` is the deprecated alias.
HF=hf; command -v hf >/dev/null 2>&1 || HF=huggingface-cli

# assemble the download list
DL=("${ORDER_80GB[@]}")
[[ "$WANT_FLASH" == "1" ]] && DL+=(dsflash)

echo "-- models targeted: ${DL[*]}"
for key in "${DL[@]}"; do
  repo="${REPO[$key]}"
  echo "==== $key  ->  $repo  [${TIER[$key]}]"
  if [[ "$ONLY_CHECK" == "1" ]]; then
    if $HF scan-cache 2>/dev/null | grep -q "$repo"; then
      echo "   present in cache"
    else
      echo "   NOT downloaded"
    fi
    continue
  fi
  # idempotent: hf cli skips already-complete files
  revision="${REVISION[$key]:-}"
  if [[ -z "$revision" ]]; then
    echo "   !! no pinned revision; refusing to download $repo"
    continue
  fi
  exclude_args=()
  if [[ -n "${DOWNLOAD_EXCLUDE[$key]:-}" ]]; then
    read -r -a exclude_patterns <<< "${DOWNLOAD_EXCLUDE[$key]}"
    for pattern in "${exclude_patterns[@]}"; do
      exclude_args+=(--exclude "$pattern")
    done
  fi
  $HF download "$repo" --revision "$revision" --quiet ${exclude_args[@]+"${exclude_args[@]}"} || {
    echo "   !! download failed for $repo, check the exact id on huggingface.co"
    echo "      and confirm this account can read the pinned snapshot"
  }
done

# Tool chat template for the Llama 3.x json parser (not in the vllm wheel).
LLAMA_TEMPLATE="$HF_HOME/tool_chat_template_llama3.1_json.jinja"
LLAMA_TEMPLATE_SHA256="8aedd05f7ab549b897b929c89da9b62e537f4f4197f33736e9d2f10fea53b1bf"
if [[ "$ONLY_CHECK" == "0" && ! -f "$LLAMA_TEMPLATE" ]]; then
  curl -fsSL -o "$LLAMA_TEMPLATE" \
    https://raw.githubusercontent.com/vllm-project/vllm/v0.27.1/examples/tool_chat_template_llama3.1_json.jinja \
    || echo "   !! could not fetch the pinned Llama tool template"
fi
if [[ -f "$LLAMA_TEMPLATE" ]]; then
  actual_template_sha256="$(sha256sum "$LLAMA_TEMPLATE" | awk '{print $1}')"
  if [[ "$actual_template_sha256" != "$LLAMA_TEMPLATE_SHA256" ]]; then
    echo "   !! Llama tool template digest mismatch" >&2
    exit 1
  fi
fi

echo
echo "== bootstrap complete. NOT starting any server (by design). =="
echo "When PJ says go, serve one model at a time with:"
echo "    bash serve.sh <key>       # keys: ${ORDER_80GB[*]} gptoss (dsflash=burst)"
echo "or let tools/runpod/sweep.sh serve, run, aggregate and stop each one in turn."
