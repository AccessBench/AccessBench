# tools

`runpod/`: serving kit for self-hosted open-weight subject models on a RunPod
GPU pod (vLLM). `models.sh` is the single source of truth for model keys,
`bootstrap.sh` installs and downloads, `serve.sh <key>` serves one model on
:8000, `model_agent.py` and `run_sweep.py` are the older adapter and sweep
scripts kept for reference. See the pod-side notes in `bootstrap.sh`.
