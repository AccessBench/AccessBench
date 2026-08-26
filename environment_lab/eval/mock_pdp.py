# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""A stand-in AuthZEN 1.0 PDP for the local HTTP seam demo.

This is a generic research integration:
an HTTP endpoint that receives an AuthZEN evaluation and returns a decision.
It never receives oracle-only fields. Here it implements a simple label-aware
policy so the seam can be demonstrated end to end; a real vendor drops in their
own engine behind the identical contract.

    POST /access/v1/evaluation  {subject,action,resource,context}
      -> {"decision": bool, "context": {"accessbench": {...}}}
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GRADED = {"model_context", "persistence", "tool_input", "app_commit"}
EGRESS = {"tool_input", "app_commit", "persistence"}
EXTERNAL = {"external", "public", "anyone_with_link", "partner"}
SENSITIVE = {"restricted", "confidential"}


def vendor_policy(ev: dict, inherited_labels: list[dict] | None = None) -> dict:
    """A vendor's own decision logic, over the event_view only."""
    boundary = ev.get("boundary")
    if boundary not in GRADED:
        return {"effect": "allow", "reason": "boundary not governed"}
    ctx = ev.get("decision_context", {})
    roles = set(ctx.get("subject", {}).get("roles", []))
    purpose = ctx.get("purpose")
    dest = ev.get("destination", {})
    labels = list(ev.get("observed_labels", []))
    if boundary in EGRESS:
        labels.extend(inherited_labels or [])
    for lab in labels:
        allowed_roles = set(lab.get("allowed_roles", []))
        allowed_purposes = set(lab.get("allowed_purposes", []))
        allowed_aud = set(lab.get("allowed_audiences", []))
        cls = lab.get("classification", "public")
        if boundary == "model_context" and allowed_roles and not (roles & allowed_roles):
            return {"effect": "deny", "reason": "vendor: role not entitled"}
        if boundary in EGRESS:
            if allowed_purposes and purpose not in allowed_purposes:
                return {"effect": "deny", "reason": "vendor: purpose not permitted"}
            if allowed_aud and dest.get("audience") not in allowed_aud:
                return {"effect": "deny", "reason": "vendor: audience not permitted"}
            if cls in SENSITIVE and dest.get("trust_zone") in EXTERNAL:
                return {"effect": "deny", "reason": "vendor: sensitive to external"}
    return {"effect": "allow", "reason": "vendor: within policy"}


def event_view_from_authzen(request: dict) -> dict:
    """Recover the policy inputs used by this demo without oracle-only data."""
    subject = request.get("subject", {})
    action = request.get("action", {})
    resource = request.get("resource", {})
    context = dict(request.get("context", {}))
    context.pop("accessbench", None)
    context["subject"] = {
        "principal_id": subject.get("id"),
        "principal_type": subject.get("type"),
        **subject.get("properties", {}),
    }
    properties = resource.get("properties", {})
    return {
        "timestamp": request.get("context", {}).get("timestamp"),
        "boundary": action.get("properties", {}).get("boundary"),
        "app": action.get("properties", {}).get("app"),
        "action": action.get("name"),
        "resource_id": resource.get("id"),
        "payload": properties.get("payload", ""),
        "destination": request.get("context", {}).get("destination", {}),
        "decision_context": context,
        "observed_labels": properties.get("observed_labels", []),
    }


class MockPDP:
    def __init__(self, host="127.0.0.1", port=0):
        policy = vendor_policy
        session_labels: dict[str, list[dict]] = {}
        session_lock = threading.Lock()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                if self.path != "/access/v1/evaluation":
                    self.send_response(404)
                    self.end_headers()
                    return
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode())
                event = event_view_from_authzen(body)
                session_id = self.headers.get(
                    "X-AccessBench-Enforcement-Session", "missing-session"
                )
                with session_lock:
                    inherited = list(session_labels.get(session_id, []))
                result = policy(event, inherited)
                if (
                    event.get("boundary") == "model_context"
                    and result["effect"] != "deny"
                ):
                    with session_lock:
                        session_labels.setdefault(session_id, []).extend(
                            event.get("observed_labels", [])
                        )
                raw = json.dumps({
                    "decision": result["effect"] != "deny",
                    "context": {"accessbench": {
                        **result,
                        "implementation": {
                            "id": "accessbench-mock-authzen",
                            "version": "1",
                        },
                        "state_scope": "episode",
                    }},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._srv = ThreadingHTTPServer((host, port), H)
        self.port = self._srv.server_address[1]
        self.url = f"http://{host}:{self.port}"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()
