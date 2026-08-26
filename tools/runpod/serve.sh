#!/usr/bin/env bash
# Launch one model's vLLM server with the correct, pinned flags.
# This serves the model; it does NOT run the benchmark. Run the sweep yourself
# in another shell once the server prints "Application startup complete".
#
#   bash serve.sh mistral24     # serve one model on :8000
#   bash serve.sh --list        # show keys
#
# Weight-swap: Ctrl-C to stop (frees VRAM) before serving the next model.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/models.sh"

key="${1:-}"
if [[ -z "$key" || "$key" == "--list" ]]; then
  echo "keys (80 GB tier): ${ORDER_80GB[*]}"
  echo "control          : gptoss"
  echo "burst (2x80 GB)  : dsflash"
  exit 0
fi
if [[ -z "${SERVE[$key]:-}" ]]; then
  echo "unknown key '$key'. try: bash serve.sh --list"; exit 1
fi
if [[ -z "${REVISION[$key]:-}" ]]; then
  echo "model '$key' has no pinned weight revision and cannot be served" >&2
  exit 2
fi

: "${HF_HOME:=/workspace/hf}"; export HF_HOME
# Bootstrap is the only networked weight step. Serving is pinned to the
# verified local snapshot and must not fetch a changed or ancillary file.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
if [[ "${TIER[$key]}" == "burst-2gpu" ]]; then
  echo "!! $key is the 2x80 GB BURST model. Confirm 2 GPUs are visible:"
  nvidia-smi --query-gpu=index,name --format=csv,noheader || true
  echo "   (Ctrl-C now if you only have one card.)"
  sleep 3
fi

echo "== serving $key  (${REPO[$key]}) on http://localhost:8000/v1 =="
echo "== when ready, in another shell (or let tools/runpod/sweep.sh drive this):"
echo "   cd environment_lab && python eval/run_eval.py --model ${REPO[$key]} --enforcement benchmark_pdp_v3"
echo
eval "${SERVE[$key]} --revision '${REVISION[$key]}'"
