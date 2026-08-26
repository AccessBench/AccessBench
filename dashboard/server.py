# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Run browser server.

Standard library only. Reads completed run results from results/summary.json
and serves the static dashboard that renders them.

    python3 dashboard/server.py
    open http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))

STATIC = ROOT / "static"
PORT = int(os.environ.get("ACCESSBENCH_DASHBOARD_PORT", "8000"))


def list_runs() -> list[dict]:
    results = REPO / "results"
    if not results.exists():
        return []
    out = []
    for d in sorted(results.iterdir(), reverse=True):
        summary = d / "summary.json"
        if d.is_dir() and summary.exists():
            try:
                meta = json.loads(summary.read_text()).get("meta", {})
            except json.JSONDecodeError:
                continue
            out.append(
                {
                    "run_id": d.name,
                    "provider": meta.get("provider"),
                    "model": meta.get("model"),
                    "episodes": meta.get("episodes_run"),
                    "publication_eligible": meta.get("publication_eligible"),
                    "pooled_headline_allowed": meta.get("pooled_headline_allowed"),
                    "fixed_bank_headline_allowed": meta.get(
                        "fixed_bank_headline_allowed"
                    ),
                    "fixed_bank_case_n": meta.get("fixed_bank_case_n"),
                    "evaluation_mode": meta.get("evaluation_mode"),
                    "panel_status": meta.get("panel_status"),
                    "k_repeats": meta.get("k_repeats"),
                    "enforcement_input": meta.get("enforcement_input"),
                    "scenario_version": meta.get("scenario_version"),
                    "harness": "v1" if meta.get("fixed_bank_case_n") is not None else "legacy",
                }
            )
    return out[:60]


_RUN_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _safe_run_id(run_id: str) -> str:
    """A results/ directory name, or '' if it could name anything else."""
    if not run_id or run_id in (".", "..") or any(c not in _RUN_ID_CHARS for c in run_id):
        return ""
    return run_id


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, path.read_bytes(), ctype)

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
        elif route == "/app.js":
            self._file(STATIC / "app.js", "application/javascript; charset=utf-8")
        elif route == "/metrics.js":
            self._file(STATIC / "metrics.js", "application/javascript; charset=utf-8")
        elif route == "/styles.css":
            self._file(STATIC / "styles.css", "text/css; charset=utf-8")
        elif route == "/api/runs":
            self._json(list_runs())
        elif route == "/api/summary":
            run_id = _safe_run_id(parse_qs(parsed.query).get("run_id", [""])[0])
            path = REPO / "results" / run_id / "summary.json" if run_id else None
            if path is None or not path.exists():
                self._json({"error": "unknown run"}, 404)
            else:
                self._json(json.loads(path.read_text()))
        elif route == "/report":
            # The readable report.html that `accessbench run` writes into the
            # bundle (0.17.0 and later). Served as is; older result directories
            # have none.
            run_id = _safe_run_id(parse_qs(parsed.query).get("run_id", [""])[0])
            path = REPO / "results" / run_id / "report.html" if run_id else None
            if path is None or not path.exists():
                self._send(404, b"no report.html in this result directory (accessbench run writes one since 0.17.0; older runs have summary.json only)", "text/plain")
            else:
                self._file(path, "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"AccessBench dashboard on http://localhost:{PORT}")
    print("  serving completed run results from results/; ctrl-c to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
