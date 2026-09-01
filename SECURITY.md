# Security Policy

AccessBench measures agentic AI governance and data exfiltration. We take
reports about the harness itself seriously, separately from anything the
benchmark is designed to surface about a model or enforcement layer under
test.

## Reporting a vulnerability

Please report security issues privately through GitHub's Security Advisories
for this repository:

https://github.com/accessbench/accessbench/security/advisories/new

Do not open a public issue for a suspected vulnerability. Include:

- affected file(s) or component,
- reproduction steps,
- impact (what an attacker gains: signature forgery, integrity-check bypass,
  scored-bank leakage, credential exposure, etc.).

We will acknowledge reports within 5 business days and aim to provide a
remediation timeline within 10 business days of confirming the issue.

## Scope

In scope: the harness, executors, Judge/Anti-Cheat pipeline, signing and
evidence code, aggregation, dashboard, and CI/release tooling in this
repository.

Out of scope: vulnerabilities in a third-party model or enforcement layer
that a user chooses to benchmark, or in third-party dependencies (report
those upstream).

## Supported versions

The supported version is the one in `VERSION` (1.0.0 at the first public
cut), developed on `main`. Security fixes land on `main` and ship in the next
release; there is no separate maintenance branch yet.
