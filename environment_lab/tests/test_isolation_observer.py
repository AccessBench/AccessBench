# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Tests for the network/filesystem isolation observer.

Most tests call `observer._observe(event, args)` directly rather than installing
a real `sys.addaudithook`: that hook can never be removed once installed (a
CPython limitation), so calling `sys.addaudithook` once per test would leave
one permanently-installed hook per test accumulated for the rest of the
pytest process. Testing the hook logic directly gets the same coverage
without that cost. One test at the bottom does install a real hook, to prove
the actual installation mechanism works end to end -- accepting that single
hook staying installed for the rest of the test run as a deliberate,
one-time cost.
"""
from __future__ import annotations

import socket
import unittest

from accessbench_env.isolation_observer import IsolationObserver, _is_sensitive_path


class SensitivePathTests(unittest.TestCase):
    def test_flags_the_private_held_out_catalog(self):
        self.assertTrue(_is_sensitive_path("/repo/environment_lab/catalog/heldout.jsonl"))

    def test_flags_private_assets(self):
        self.assertTrue(_is_sensitive_path("/repo/environment_lab/private_assets/seed.txt"))

    def test_flags_ssh_credentials(self):
        self.assertTrue(_is_sensitive_path("/Users/someone/.ssh/id_ed25519"))

    def test_flags_aws_credentials(self):
        self.assertTrue(_is_sensitive_path("/Users/someone/.aws/credentials"))

    def test_does_not_flag_an_ordinary_python_stdlib_import(self):
        self.assertFalse(_is_sensitive_path("/opt/anaconda3/lib/python3.12/socket.py"))

    def test_does_not_flag_the_repo_s_own_public_catalog(self):
        self.assertFalse(_is_sensitive_path("/repo/environment_lab/catalog/core_v2.jsonl"))

    def test_macos_private_temp_prefix_is_not_the_repo_private_dir(self):
        """On macOS /tmp and the per-user temp dirs resolve under /private.
        A checkout or a tempfile there is ordinary; only the repository's own
        private/ directory (or a real private/ deeper in the path) counts."""
        self.assertFalse(_is_sensitive_path("/private/var/folders/ab/T/tmpq1/signing-key.pem"))
        self.assertFalse(_is_sensitive_path("/private/tmp/checkout/accessbench/environment_lab/catalog/core_v2.jsonl"))
        self.assertTrue(_is_sensitive_path("/private/tmp/checkout/accessbench/private/legal.md"))
        self.assertTrue(_is_sensitive_path("/Users/someone/accessbench/private/legal.md"))
        self.assertTrue(_is_sensitive_path("/private/tmp/checkout/accessbench/internal/notes.md"))

    def test_does_not_flag_an_unrelated_sibling_project(self):
        """The exact case a live capture surfaced during development: Python's
        own package/entry-point scanning touching an unrelated sibling
        project directory. This must not be flagged -- see the module
        docstring on why a denylist, not a strict allowlist, was chosen.
        """
        self.assertFalse(
            _is_sensitive_path(
                "/Users/someone/Projects/other-project/some.egg-info/entry_points.txt"
            )
        )


class IsolationObserverHookLogicTests(unittest.TestCase):
    """Exercises _observe() directly; installs no real audit hook."""

    def setUp(self):
        # Loopback only: no real DNS lookups in a unit test.
        self.observer = IsolationObserver(["localhost"])

    def test_connect_to_an_allowed_ip_is_not_a_violation(self):
        self.observer.allowed_ips = {"93.184.216.34"}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sock.close)
        self.observer._observe("socket.connect", (sock, ("93.184.216.34", 443)))
        self.assertEqual(self.observer.network_violations, [])

    def test_connect_to_an_unlisted_ip_is_a_violation(self):
        self.observer.allowed_ips = {"93.184.216.34"}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sock.close)
        self.observer._observe("socket.connect", (sock, ("198.51.100.7", 443)))
        self.assertEqual(len(self.observer.network_violations), 1)
        self.assertEqual(
            self.observer.network_violations[0]["destination_ip"], "198.51.100.7"
        )

    def test_loopback_is_always_allowed_regardless_of_declared_hosts(self):
        self.observer.allowed_ips = {"93.184.216.34"}  # deliberately excludes loopback
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sock.close)
        self.observer._observe("socket.connect", (sock, ("127.0.0.1", 8000)))
        self.assertEqual(self.observer.network_violations, [])

    def test_opening_a_sensitive_path_is_a_violation(self):
        self.observer._observe("open", ("/Users/someone/.ssh/id_ed25519", "r", 0))
        self.assertEqual(len(self.observer.filesystem_violations), 1)

    def test_opening_an_ordinary_path_is_not_a_violation(self):
        self.observer._observe("open", ("/opt/anaconda3/lib/python3.12/socket.py", "r", 0))
        self.assertEqual(self.observer.filesystem_violations, [])

    def test_a_malformed_event_never_raises(self):
        """The hook must never raise: see the module docstring. A malformed
        or unexpected args tuple should be silently ignored, not crash
        whatever real file open or connect triggered it.
        """
        try:
            self.observer._observe("socket.connect", ())
            self.observer._observe("socket.connect", (None,))
            self.observer._observe("open", ())
            self.observer._observe("unrelated.event", (1, 2, 3))
        except Exception as exc:  # pragma: no cover - the assertion is that this never runs
            self.fail(f"_observe raised: {exc}")

    def test_report_reflects_pass_when_nothing_was_observed(self):
        report = self.observer.report()
        self.assertEqual(report["network_isolation"]["state"], "pass")
        self.assertEqual(report["filesystem_isolation"]["state"], "pass")

    def test_report_reflects_fail_when_a_violation_was_recorded(self):
        self.observer.filesystem_violations.append({"path": "/Users/someone/.aws/credentials"})
        report = self.observer.report()
        self.assertEqual(report["filesystem_isolation"]["state"], "fail")
        self.assertEqual(report["network_isolation"]["state"], "pass")


class AllowedIpResolutionTests(unittest.TestCase):
    def test_a_literal_ip_host_is_used_as_is(self):
        observer = IsolationObserver(["93.184.216.34"])
        self.assertIn("93.184.216.34", observer.allowed_ips)

    def test_localhost_resolves_to_loopback_addresses(self):
        observer = IsolationObserver(["localhost"])
        self.assertTrue({"127.0.0.1", "::1"} & observer.allowed_ips)

    def test_an_unresolvable_host_does_not_raise(self):
        try:
            IsolationObserver(["this-host-does-not-exist.invalid"])
        except Exception as exc:
            self.fail(f"resolving an unresolvable host raised: {exc}")


class RealAuditHookInstallationTests(unittest.TestCase):
    """The one test in this file that installs a real, permanent audit hook,
    to prove the actual mechanism works end to end. Deliberately singular:
    each `sys.addaudithook` call adds a hook that lasts for the rest of the
    process, so this is a one-time cost, not a per-test one.
    """

    def test_a_real_connect_through_the_installed_hook_is_observed(self):
        observer = IsolationObserver(["203.0.113.5"])  # TEST-NET-3, deliberately unreachable
        with observer:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            try:
                sock.connect(("198.51.100.9", 9))  # TEST-NET-2, not the declared host
            except OSError:
                pass  # connection failing is fine; the audit event still fires
            finally:
                sock.close()
        self.assertTrue(
            any(v["destination_ip"] == "198.51.100.9" for v in observer.network_violations)
        )


class NoHookAccumulationTests(unittest.TestCase):
    """Regression guard: an earlier version of this module installed a new
    real sys.addaudithook on every `with observer:`, and since a real hook
    can never be removed, that accumulated one permanently-installed hook
    per use -- a real, measured slowdown across the test suite, since
    run_eval_arm (which uses this) runs many times per pytest process.
    """

    def test_many_context_manager_uses_install_at_most_one_real_hook(self):
        import accessbench_env.isolation_observer as module

        installed_before = module._dispatch_hook_installed
        for _ in range(50):
            with IsolationObserver(["localhost"]):
                pass
        self.assertTrue(module._dispatch_hook_installed)
        # Once installed, it stays installed (cannot be removed); the
        # regression this guards against is a NEW hook per use, not the
        # existence of the one hook itself.
        if installed_before:
            self.assertTrue(module._dispatch_hook_installed)

    def test_observers_do_not_leak_into_each_other_via_the_shared_dispatch(self):
        first = IsolationObserver(["localhost"])
        second = IsolationObserver(["localhost"])
        with first:
            first._observe("open", ("/Users/someone/.ssh/id_rsa", "r", 0))
        with second:
            second._observe("socket.connect", (None, ("198.51.100.9", 443)))
        self.assertEqual(len(first.filesystem_violations), 1)
        self.assertEqual(len(second.filesystem_violations), 0)
        self.assertEqual(len(second.network_violations), 1)
        self.assertEqual(len(first.network_violations), 0)


if __name__ == "__main__":
    unittest.main()
