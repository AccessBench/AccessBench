# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(LAB_ROOT / "eval"))

from accessbench_env.conformance import run_conformance
from accessbench_env.enforcers import HttpEnforcer
from mock_pdp import MockPDP


class _BrokenPDP:
    """Non-boolean decision, no implementation identity, flips on repeat."""

    def __init__(self):
        calls = {"n": 0}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                calls["n"] += 1
                raw = json.dumps({
                    "decision": "yes" if calls["n"] == 1 else (calls["n"] % 2 == 0),
                    "context": {"accessbench": {}},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()


class TestConformance(unittest.TestCase):
    def test_reference_mock_pdp_passes(self):
        pdp = MockPDP().start()
        try:
            report = run_conformance(pdp.url)
        finally:
            pdp.stop()
        self.assertTrue(report["ok"], report)
        states = {name: c["state"] for name, c in report["checks"].items()}
        for name in (
            "endpoint_shape", "reachable", "boolean_decision", "context_object",
            "implementation_identity", "state_scope_declared", "rewrite_shape",
            "deterministic",
        ):
            self.assertEqual(states[name], "pass", name)
        self.assertEqual(states["denies_obvious_egress"], "pass")
        self.assertIn(report["latency_ms"]["median"], report["latency_ms"].values())

    def test_broken_pdp_fails_with_reasons(self):
        pdp = _BrokenPDP().start()
        try:
            report = run_conformance(pdp.url)
        finally:
            pdp.stop()
        self.assertFalse(report["ok"])
        states = {name: c["state"] for name, c in report["checks"].items()}
        self.assertEqual(states["boolean_decision"], "fail")
        self.assertEqual(states["implementation_identity"], "fail")
        self.assertEqual(states["state_scope_declared"], "fail")

    def test_endpoint_shape_rejects_credentials_and_unreachable(self):
        report = run_conformance("http://user:pw@127.0.0.1:1/access/v1/evaluation")
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"]["endpoint_shape"]["state"], "fail")
        report = run_conformance("http://127.0.0.1:9", timeout=0.5)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"]["reachable"]["state"], "fail")


class _ContradictoryPDP:
    """Says allow in the AuthZEN boolean and deny in the AccessBench extension."""

    def __init__(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                raw = json.dumps({
                    "decision": True,
                    "context": {"accessbench": {
                        "effect": "deny",
                        "reason": "vendor believes this is denied",
                        "implementation": {"id": "contradictory", "version": "1"},
                        "state_scope": "none",
                    }},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()


class TestContradictoryDecision(unittest.TestCase):
    def test_allow_boolean_with_deny_extension_fails_closed(self):
        """An ambiguous authorization answer must not resolve to allow.

        AuthZEN's boolean is the decision, and the AccessBench extension may
        only narrow an allow to a rewrite. A response that says allow in one
        field and deny in another is not a decision, it is a contract error,
        and a security gate resolves those closed.
        """
        pdp = _ContradictoryPDP().start()
        try:
            enforcer = HttpEnforcer(pdp.url, timeout=5.0)
            decision = enforcer.decide({
                "boundary": "tool_input", "app": "a", "action": "x",
                "resource_id": "r", "payload": "p", "destination": {},
                "decision_context": {"subject": {}}, "observed_labels": [],
            })
            self.assertEqual(decision.effect, "deny")
            self.assertTrue(enforcer.errors)
            self.assertIn("contradict", " ".join(enforcer.errors).lower())
            report = run_conformance(pdp.url, timeout=5.0)
            self.assertEqual(report["checks"]["decision_consistency"]["state"], "fail")
            self.assertFalse(report["ok"])
        finally:
            pdp.stop()


class _HangingPDP:
    """Accepts the connection and never answers."""

    def __init__(self):
        import socket
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.url = f"http://127.0.0.1:{self._sock.getsockname()[1]}"
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        self._sock.settimeout(0.2)
        conns = []
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
                conns.append(conn)  # hold it open, never respond
            except OSError:
                continue
        for c in conns:
            c.close()

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()
        self._t.join(timeout=2)
        self._sock.close()


class TestTimeoutEndpoint(unittest.TestCase):
    def test_hanging_pdp_fails_closed_and_conformance_reports_unreachable(self):
        """A decision point that never answers is a deny, and conformance says so."""
        pdp = _HangingPDP().start()
        try:
            enforcer = HttpEnforcer(pdp.url, timeout=0.5)
            decision = enforcer.decide({
                "boundary": "tool_input", "app": "a", "action": "x",
                "resource_id": "r", "payload": "p", "destination": {},
                "decision_context": {"subject": {}}, "observed_labels": [],
            })
            self.assertEqual(decision.effect, "deny")
            self.assertTrue(any("unreachable" in e for e in enforcer.errors))
            report = run_conformance(pdp.url, timeout=0.5)
            self.assertFalse(report["ok"])
            self.assertEqual(report["checks"]["reachable"]["state"], "fail")
        finally:
            pdp.stop()


if __name__ == "__main__":
    unittest.main()
