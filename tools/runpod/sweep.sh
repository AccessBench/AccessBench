#!/usr/bin/env bash
# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
#
# AccessBench local-model sweep for one GPU box. For each roster key it
# serves the model with vLLM, waits until the endpoint answers, runs the
# paired benchmark (eval/run_eval.py, which adds the no-enforcement arm on
# its own), aggregates the result, stops the server to free VRAM, and moves
# to the next key. Resume on failure, same as tools/overnight.sh.
#
#   bash tools/runpod/sweep.sh qwen32 mistral24 qwencoder30 gptoss llama70
#
# Environment (all optional):
#   ENFORCEMENT   built-in gate or AuthZEN URL   (default benchmark_pdp_v3)
#   ATTEMPTS      run attempts per model, resume  (default 3)
#   HARNESS_PY    python with the harness installed
#                 (default environment_lab/.venv/bin/python)
#   VLLM_ACTIVATE a venv activate script for vLLM, sourced before serving
#                 (default /workspace/venv/bin/activate if it exists)
#   HF_HOME       weight cache                    (default /workspace/hf)
#   PORT          vLLM port                        (default 8000)
#   READY_WAIT_S  seconds to wait for the server  (default 1800)
#   SMOKE_TRIALS  development pilot case count     (unset means full 600)
#   DRY_RUN=1     print the plan, run nothing
#   HOLD_FILE     finish the active model, then stop before another is served
#                 (default /workspace/HOLD)
#
# Local endpoints are exempt from the spend guard; this script never calls a
# hosted API. Development-bank runs are never publication eligible.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LAB="$ROOT/environment_lab"
ENFORCEMENT="${ENFORCEMENT:-benchmark_pdp_v3}"
ATTEMPTS="${ATTEMPTS:-3}"
HARNESS_PY="${HARNESS_PY:-$LAB/.venv/bin/python}"
PORT="${PORT:-8000}"
READY_WAIT_S="${READY_WAIT_S:-1800}"
SMOKE_TRIALS="${SMOKE_TRIALS:-}"
HOLD_FILE="${HOLD_FILE:-/workspace/HOLD}"
if [[ "$PORT" != "8000" ]]; then
  echo "the pinned serve roster uses port 8000; PORT overrides are not supported" >&2
  exit 2
fi
: "${HF_HOME:=/workspace/hf}"; export HF_HOME
if [[ -z "${VLLM_ACTIVATE:-}" && -f /workspace/venv/bin/activate ]]; then
  VLLM_ACTIVATE=/workspace/venv/bin/activate
fi
LOGDIR="$LAB/results_raw/logs"; mkdir -p "$LOGDIR"
STATUS="$LAB/results_raw/sweep_status.txt"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
if [[ -f "$STATUS" ]]; then
  mv "$STATUS" "$LOGDIR/sweep-status-before-$RUN_ID.txt"
fi
: > "$STATUS"
export ACCESSBENCH_MODEL_BASE_URL="http://localhost:$PORT/v1"
export ACCESSBENCH_SIGNING_KEY="${ACCESSBENCH_SIGNING_KEY:-$HOME/.accessbench/signing.key}"
export ACCESSBENCH_REQUIRE_PINNED_LOCAL=yes
unset ACCESSBENCH_RESUME_RAW ACCESSBENCH_SMOKE_TRIALS ACCESSBENCH_SPEND_APPROVED
if [[ -n "$SMOKE_TRIALS" ]]; then
  if [[ ! "$SMOKE_TRIALS" =~ ^[1-9][0-9]*$ ]] || (( SMOKE_TRIALS > 600 )); then
    echo "SMOKE_TRIALS must be an integer from 1 through 600" >&2
    exit 2
  fi
  export ACCESSBENCH_SMOKE_TRIALS="$SMOKE_TRIALS"
fi

# shellcheck source=models.sh
source "$HERE/models.sh"

if git -C "$ROOT" rev-parse HEAD >/dev/null 2>&1; then
  export ACCESSBENCH_HARNESS_GIT_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    export ACCESSBENCH_HARNESS_GIT_DIRTY=yes
  else
    export ACCESSBENCH_HARNESS_GIT_DIRTY=no
  fi
elif [[ -z "${ACCESSBENCH_HARNESS_GIT_COMMIT:-}" ]]; then
  echo "no Git checkout on pod; export ACCESSBENCH_HARNESS_GIT_COMMIT to the deployed tag commit" >&2
  exit 2
fi

ORCHESTRATOR_SHA256="$({
  cd "$HERE" || exit 1
  sha256sum models.sh serve.sh sweep.sh preflight_model.py
} | sha256sum | awk '{print $1}')"
export ACCESSBENCH_MODEL_ORCHESTRATOR_SHA256="$ORCHESTRATOR_SHA256"

stamp() { date -u +"%Y-%m-%d %H:%M"; }
log() { echo "$(stamp) run=$RUN_ID $*" | tee -a "$STATUS"; }
hold_requested() { [[ -e "$HOLD_FILE" ]]; }

if [[ $# -eq 0 ]]; then
  echo "usage: bash tools/runpod/sweep.sh KEY [KEY ...]   (keys: ${!REPO[*]})" >&2
  exit 2
fi
for key in "$@"; do
  [[ -n "${REPO[$key]:-}" ]] || { echo "unknown key '$key'. keys: ${!REPO[*]}" >&2; exit 2; }
done
[[ -x "$HARNESS_PY" ]] || { echo "harness python not found at $HARNESS_PY (set HARNESS_PY)" >&2; exit 2; }
[[ -f "$ACCESSBENCH_SIGNING_KEY" ]] || {
  echo "no signing key at $ACCESSBENCH_SIGNING_KEY; create one:" >&2
  echo "  cd $LAB && $HARNESS_PY -m accessbench_env generate-signing-key --out $ACCESSBENCH_SIGNING_KEY" >&2
  exit 2; }

gpu_pids() { nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ' | grep -E '^[0-9]+$' || true; }

stop_server() {
  # Kill the serve.sh process group first, then anything still holding the GPU.
  # Never `pkill -f vllm`: it matches this shell's own command line.
  if [[ -n "${SERVE_PGID:-}" ]]; then kill -TERM -- "-$SERVE_PGID" 2>/dev/null || true; fi
  for p in $(gpu_pids); do kill -TERM "$p" 2>/dev/null || true; done
  local t=0
  while [[ -n "$(gpu_pids)" && $t -lt 120 ]]; do sleep 5; t=$((t+5)); done
  for p in $(gpu_pids); do kill -KILL "$p" 2>/dev/null || true; done
  sleep 5
  SERVE_PGID=""
}
trap 'log "interrupted; stopping server"; stop_server; exit 130' INT TERM

wait_ready() {
  local repo="$1" t=0
  while [[ $t -lt $READY_WAIT_S ]]; do
    if curl -fsS "http://localhost:$PORT/v1/models" 2>/dev/null | grep -q "\"$repo\""; then return 0; fi
    if [[ -n "${SERVE_PID:-}" ]] && ! kill -0 "$SERVE_PID" 2>/dev/null; then
      log "server process exited before ready; see $LOGDIR/serve-$key.log"; return 1; fi
    sleep 10; t=$((t+10))
  done
  log "server not ready after ${READY_WAIT_S}s"; return 1
}

log "SWEEP start: keys=[$*] enforcement=$ENFORCEMENT HF_HOME=$HF_HOME port=$PORT smoke=${SMOKE_TRIALS:-full} hold_file=$HOLD_FILE"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null | sed 's/^/  gpu: /' | tee -a "$STATUS"

for key in "$@"; do
  if hold_requested; then
    log "HOLD before $key: $HOLD_FILE exists; no new model will be served"
    break
  fi
  REPO_ID="${REPO[$key]}"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "DRY: serve $key ($REPO_ID) then: $HARNESS_PY eval/run_eval.py --model $REPO_ID --enforcement $ENFORCEMENT"; continue
  fi
  if [[ "${TIER[$key]}" == "burst-2gpu" ]]; then log "SKIP $key: burst tier needs 2 GPUs; run it by hand"; continue; fi
  if [[ "${TRIAL_ENABLED[$key]:-no}" != "yes" ]]; then log "SKIP $key: roster excludes it from full trials"; continue; fi
  if [[ -z "${REVISION[$key]:-}" ]]; then log "SKIP $key: no pinned weight revision"; continue; fi
  if [[ -n "$(gpu_pids)" ]]; then log "GPU busy before $key (pids: $(gpu_pids | tr '\n' ' ')); stopping"; stop_server; fi

  log "SERVE $key ($REPO_ID)"
  (
    [[ -n "${VLLM_ACTIVATE:-}" ]] && source "$VLLM_ACTIVATE"
    exec setsid bash "$HERE/serve.sh" "$key"
  ) >"$LOGDIR/serve-$key.log" 2>&1 &
  SERVE_PID=$!
  sleep 2
  SERVE_PGID="$(ps -o pgid= -p "$SERVE_PID" 2>/dev/null | tr -d ' ')"
  if ! wait_ready "$REPO_ID"; then log "FAILED $key: server never came up"; stop_server; continue; fi
  log "READY $key"

  PREFLIGHT="$LOGDIR/preflight-$key.json"
  if ! "$HARNESS_PY" "$HERE/preflight_model.py" \
      --model "$REPO_ID" --base-url "$ACCESSBENCH_MODEL_BASE_URL" \
      >"$PREFLIGHT"; then
    log "FAILED $key: tool-call preflight failed; see $PREFLIGHT"
    stop_server
    continue
  fi
  export ACCESSBENCH_MODEL_PREFLIGHT_SHA256
  ACCESSBENCH_MODEL_PREFLIGHT_SHA256="$(sha256sum "$PREFLIGHT" | awk '{print $1}')"
  export ACCESSBENCH_MODEL_REVISION="$REPO_ID"
  export ACCESSBENCH_MODEL_WEIGHT_REVISION="${REVISION[$key]}"
  export ACCESSBENCH_MODEL_QUANTIZATION="${QUANT[$key]}"
  export ACCESSBENCH_MODEL_SERVER_SOFTWARE="vllm"
  ACCESSBENCH_MODEL_SERVER_VERSION="$(curl -fsS "http://localhost:$PORT/version" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  export ACCESSBENCH_MODEL_SERVER_VERSION
  if [[ -z "$ACCESSBENCH_MODEL_SERVER_VERSION" ]]; then
    log "FAILED $key: could not bind vLLM version"
    stop_server
    continue
  fi
  export ACCESSBENCH_MODEL_SERVER_CONFIG_SHA256
  ACCESSBENCH_MODEL_SERVER_CONFIG_SHA256="$(printf '%s' "${SERVE[$key]} --revision ${REVISION[$key]}" | sha256sum | awk '{print $1}')"
  log "PREFLIGHT PASS $key: revision=${REVISION[$key]} vllm=$ACCESSBENCH_MODEL_SERVER_VERSION"

  RAW=""; ok=0
  for attempt in $(seq 1 "$ATTEMPTS"); do
    if [[ -n "$RAW" ]]; then export ACCESSBENCH_RESUME_RAW="$RAW"; else unset ACCESSBENCH_RESUME_RAW; fi
    OUT="$LOGDIR/run-$key-attempt$attempt.log"
    ( cd "$LAB" && "$HARNESS_PY" eval/run_eval.py --model "$REPO_ID" --enforcement "$ENFORCEMENT" ) >"$OUT" 2>&1
    rc=$?
    NEWRAW="$(sed -n 's/^RAW_PATH=//p' "$OUT" | head -1)"
    [[ -n "$NEWRAW" ]] && RAW="$NEWRAW"
    if [[ $rc -eq 0 ]] && grep -q "^DONE" "$OUT"; then ok=1; break; fi
    if [[ -n "$RAW" && -f "$RAW" && -f "$RAW.manifest.json" ]]; then
      log "attempt $attempt for $key exited $rc; resuming $RAW in 30 s"
    else
      RAW=""
      unset ACCESSBENCH_RESUME_RAW
      log "attempt $attempt for $key exited $rc before a resumable raw; starting fresh in 30 s"
    fi
    if ! curl -fsS "http://localhost:$PORT/v1/models" >/dev/null 2>&1; then
      if hold_requested; then
        log "HOLD after server loss for $key: leaving raw resumable"
        break
      fi
      log "server went away mid-run; restarting it"
      stop_server
      ( [[ -n "${VLLM_ACTIVATE:-}" ]] && source "$VLLM_ACTIVATE"; exec setsid bash "$HERE/serve.sh" "$key" ) >>"$LOGDIR/serve-$key.log" 2>&1 &
      SERVE_PID=$!; sleep 2; SERVE_PGID="$(ps -o pgid= -p "$SERVE_PID" 2>/dev/null | tr -d ' ')"
      wait_ready "$REPO_ID" || break
    fi
    sleep 30
  done
  if [[ $ok -ne 1 ]]; then log "FAILED $key after $ATTEMPTS attempts; raw=$RAW"; stop_server; continue; fi

  MANIFEST="$RAW.manifest.json"
  MANIFEST_MODEL="$("$HARNESS_PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["config"]["model"])' "$MANIFEST")"
  if [[ "$MANIFEST_MODEL" != "$REPO_ID" ]]; then
    log "FAILED $key: manifest model $MANIFEST_MODEL does not match $REPO_ID"
    stop_server
    continue
  fi

  N=$(grep -c '' "$RAW"); ERR=$(grep -c '"error":' "$RAW" || true)
  log "DONE $key: $N episodes, $ERR error records, raw=$(basename "$RAW")"
  STAMP=$(date -u +%Y%m%d-%H%M%S)
  if ( cd "$LAB" && "$HARNESS_PY" eval/aggregate.py --raw "$RAW" --stamp "$STAMP" --provider vllm ) >"$LOGDIR/aggregate-$key.log" 2>&1; then
    SUMMARY=$(grep -o 'results/[^ ]*summary.json' "$LOGDIR/aggregate-$key.log" | tail -1)
    log "AGGREGATED $key -> ${SUMMARY:-see $LOGDIR/aggregate-$key.log}"
  else
    log "AGGREGATE FAILED $key; see $LOGDIR/aggregate-$key.log"
  fi
  stop_server
  log "STOPPED $key; VRAM free"
  if hold_requested; then
    log "HOLD after $key: active model finished; no next model will be served"
    break
  fi
done
log "SWEEP end"
