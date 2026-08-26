# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Positive-control observer for the network_isolation and filesystem_isolation
checks in registry_executor.py's protocol-check registry.

The harness is one Python process with no OS-level sandbox: the five "apps"
are simulated in memory (sandbox.py), and the only real I/O a run should do is
one HTTPS connection to the declared model endpoint plus ordinary file access
under this repo, the Python install, and ~/.accessbench. This module observes
what actually happened during a run via `sys.addaudithook` and reports two
things: any network connection outside the declared model endpoint, and any
file access matching a denylist of genuinely sensitive paths (the private
corpus, operator credentials).

Why a denylist, not a strict allowlist, for the filesystem check: a live
capture during development showed Python's own package/entry-point discovery
touching files in a completely unrelated sibling project directory on the
machine it ran on -- ordinary packaging-ecosystem noise, not a real problem,
but proof that a strict "anything outside an explicit allowlist fails" check
would be flaky across machines with different installed packages. A denylist
of what's actually sensitive is more robust and still catches the case that
matters: the process reading the private held-out corpus or credentials it
has no business touching. This is a narrower, more honest claim than true
default-deny isolation, and the module docstring says so rather than
overclaiming.

`sys.addaudithook` cannot be removed once installed (a CPython limitation),
so the hook function must never raise: an audit hook that raises makes the
audited operation itself raise, which would mean a bug in this file could
break every future file open or socket connect in the process for tests or
any other code sharing the interpreter, not just this run.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path
from typing import Any

ISOLATION_REPORT_SCHEMA_VERSION = "accessbench-isolation-report-v1"

# Substrings, not exact paths: matched against the normalized (forward-slash)
# form of every opened path. Deliberately narrow and specific -- this is a
# denylist of what's actually sensitive, not an attempt to catch everything
# unfamiliar (see the module docstring for why).
SENSITIVE_PATH_PATTERNS = (
    "/catalog/heldout.jsonl",
    "/catalog/heldout_validation.json",
    "/private_assets/",
    "/sealed_packs/",
    "/private/",
    "/internal/",
    "/.ssh/",
    "/.aws/",
    "/.gnupg/",
    "/.docker/config.json",
    "/.netrc",
    "/.config/gh/",
    "/.npmrc",
    "/.pypirc",
)


def _is_sensitive_path(path: str) -> bool:
    normalized = "/" + str(path).replace("\\", "/").lstrip("/")
    # macOS mounts /tmp and the per-user temp directories under /private
    # (/private/tmp, /private/var/folders/...). That leading system prefix is
    # not the repository's private/ directory, so strip it once before the
    # substring match; "/private/" deeper in the path still matches.
    if normalized.startswith("/private/"):
        normalized = normalized[len("/private"):]
    return any(pattern in normalized for pattern in SENSITIVE_PATH_PATTERNS)


def _resolve_allowed_ips(hosts: list[str]) -> set[str]:
    """Resolve each declared host to the IPs a real connection may land on.

    Real captures during development showed the actual connect() target was
    a raw IP (the model endpoint is Cloudflare-fronted), not the hostname, so
    a static host allowlist alone would never match. Resolving here, once,
    at observer setup, is what makes the comparison work.
    """
    ips: set[str] = set()
    for host in hosts:
        if not host:
            continue
        if host in ("localhost",):
            ips.update({"127.0.0.1", "::1"})
            continue
        try:
            ipaddress.ip_address(host)
            ips.add(host)
            continue
        except ValueError:
            pass
        try:
            for info in socket.getaddrinfo(host, None):
                ips.add(info[4][0])
        except OSError:
            pass  # unresolvable host: nothing to allow, not an error here
    return ips


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


class IsolationObserver:
    """Installs one process-lifetime audit hook and records violations.

    Construct with the hostnames a run is expected to reach (typically the
    model endpoint and, if different, the Judge endpoint). Loopback
    connections are always allowed regardless of the declared hosts, since a
    locally served model is a normal, legitimate configuration.
    """

    def __init__(self, allowed_hosts: list[str]):
        self.allowed_ips = _resolve_allowed_ips(allowed_hosts)
        self.network_violations: list[dict[str, Any]] = []
        self.filesystem_violations: list[dict[str, Any]] = []
        self._previous_observer: "IsolationObserver | None" = None

    def _observe(self, event: str, args: tuple) -> None:
        try:
            if event == "socket.connect":
                self._observe_connect(args)
            elif event == "open":
                self._observe_open(args)
        except Exception:
            # Never raise here: see the module docstring. A bug in this
            # method must be invisible, not break real file/network access.
            pass

    def _observe_connect(self, args: tuple) -> None:
        if len(args) < 2:
            return
        addr = args[1]
        if not isinstance(addr, tuple) or not addr:
            return
        ip = addr[0]
        if not isinstance(ip, str) or _is_loopback(ip):
            return
        if ip not in self.allowed_ips:
            self.network_violations.append({"destination_ip": ip})

    def _observe_open(self, args: tuple) -> None:
        if not args:
            return
        path = str(args[0])
        if _is_sensitive_path(path):
            self.filesystem_violations.append({"path": path})

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": ISOLATION_REPORT_SCHEMA_VERSION,
            "allowed_ips": sorted(self.allowed_ips),
            "network_isolation": {
                "state": "pass" if not self.network_violations else "fail",
                "violations": self.network_violations,
            },
            "filesystem_isolation": {
                "state": "pass" if not self.filesystem_violations else "fail",
                "violations": self.filesystem_violations,
            },
        }

    def __enter__(self) -> "IsolationObserver":
        global _active_observer
        _ensure_dispatch_hook_installed()
        self._previous_observer = _active_observer
        _active_observer = self
        return self

    def __exit__(self, *exc_info: object) -> bool:
        global _active_observer
        _active_observer = self._previous_observer
        return False


# A real sys.addaudithook can never be removed once installed (a CPython
# limitation), so this module installs at most one, ever, regardless of how
# many times IsolationObserver is used in one process. Each `with observer:`
# just swaps which observer the one installed hook currently delegates to.
# Installing a fresh real hook per call -- the first version of this module
# did -- accumulates hooks across a long-running process (notably the test
# suite, which exercises run_eval_arm many times), and every accumulated
# hook runs on every subsequent file open and socket connect for the rest of
# the process, compounding into a real, measured slowdown.
_active_observer: "IsolationObserver | None" = None
_dispatch_hook_installed = False


def _dispatch_hook(event: str, args: tuple) -> None:
    observer = _active_observer
    if observer is not None:
        observer._observe(event, args)


def _ensure_dispatch_hook_installed() -> None:
    global _dispatch_hook_installed
    if not _dispatch_hook_installed:
        sys.addaudithook(_dispatch_hook)
        _dispatch_hook_installed = True
