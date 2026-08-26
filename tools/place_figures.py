#!/usr/bin/env python3
"""Swap the [INSERT ...] placeholders for the generated figures.

Two placeholders are removed rather than filled. Both restate a paragraph that
is already on the page, and a figure that only repeats the sentence above it
slows a reader down instead of helping.

Run once from the repository root: python3 tools/place_figures.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# file -> list of (marker substring, replacement or None to drop)
FILL = {
    "README.md": [
        ("Model and Enforcement enter the harness",
         "![Two inputs, a model endpoint and an enforcement endpoint, enter the "
         "harness; the same 600 fixed cases run once with no enforcement and "
         "once with the enforcement layer under test; one signed results file "
         "comes out](docs/assets/fig-run.svg)"),
        ("the 600-case bank as a grid", None),
    ],
    "docs/01-design.md": [
        ("the paired experiment",
         "![One fixed bank of 600 cases feeds two arms, the agent alone and the "
         "same agent with the enforcement layer; the same deterministic grader "
         "scores both and the result is a pair of percentages]"
         "(assets/fig-paired.svg)"),
    ],
    "docs/02-methodology.md": [
        ("one model and one enforcement input enter the harness", None),
        ("the enforcement seam",
         "![The agent raises a boundary event, the enforcement layer allows, "
         "denies or rewrites it, and the sandbox commits what was allowed; the "
         "enforcement layer sees the request and its context while only the "
         "grader holds the planted values, the lineage and the answer key]"
         "(assets/fig-seam.svg)"),
        ("the AccessBricks two-arm construction",
         "![One agent and one task set run under a broad grant and under a "
         "governed identity against the same Unity Catalog warehouse, with "
         "grading at the egress boundary](assets/fig-bricks.svg)"),
    ],
    "docs/03-scope.md": [
        ("Model and Enforcement inputs entering the harness",
         "![Two inputs and the built-in none control feed one run, which "
         "returns a single signed file holding the deterministic score and the "
         "Anti-Cheat status in separate sections](assets/fig-result.svg)"),
        ("the 600-case bank as 25 leak types",
         "![Twenty five leak types by six workflows makes 150 independently "
         "grounded workflows; four request surfaces each brings the bank to 600 "
         "scored cases](assets/fig-bank.svg)"),
    ],
    "docs/04-setup.md": [
        ("the three model paths",
         "![The offline path proves the grader with no model attached; the "
         "hosted and self-hosted paths both reach the same run interface, whose "
         "raw events are aggregated into a summary the dashboard reads]"
         "(assets/fig-setup.svg)"),
    ],
    "docs/06-integrity.md": [
        ("sealed pack lifecycle",
         "![The panel is selected, shuffled and padded to a fixed record size, "
         "encrypted record by record, and scheduled by opaque handle; four "
         "checks at aggregation time verify the run against the sealed digest]"
         "(assets/fig-sealed.svg)"),
    ],
    "docs/07-validation.md": [
        ("one run's path from pre-run signed commitment",
         "![A run passes eight gates in order, from the commitment signed "
         "before inference through evidence, identity, Anti-Cheat, isolation "
         "and spend approval, before it is eligible for publication]"
         "(assets/fig-gates.svg)"),
    ],
    "docs/10-replication.md": [
        ("ledger to prompt module to core catalog",
         "![Each build step is bound to the one before it by a named digest, "
         "from the reviewed prompt ledger through the catalog, panel, run "
         "manifest and raw events to the summary](assets/fig-digests.svg)"),
    ],
}


def main():
    changed, dropped, missed = 0, 0, []
    for rel, jobs in FILL.items():
        path = os.path.join(ROOT, rel)
        with open(path) as f:
            src = f.read()
        for marker, repl in jobs:
            pat = re.compile(r"^\[INSERT [^\]]*" + re.escape(marker) +
                             r"[^\]]*\]\n", re.M)
            if not pat.search(src):
                missed.append((rel, marker))
                continue
            if repl is None:
                src = pat.sub("", src, count=1)
                # collapse the blank line the placeholder left behind
                src = re.sub(r"\n\n\n+", "\n\n", src)
                dropped += 1
            else:
                src = pat.sub(lambda m: repl + "\n", src, count=1)
                changed += 1
        with open(path, "w") as f:
            f.write(src)
    print(f"filled {changed}, dropped {dropped}")
    if missed:
        print("NOT FOUND:", missed)
        sys.exit(1)
    left = []
    for dirpath, _, names in os.walk(ROOT):
        if "/internal" in dirpath or "/.git" in dirpath or "/vendor" in dirpath:
            continue
        for n in names:
            if n.endswith(".md"):
                p = os.path.join(dirpath, n)
                with open(p) as f:
                    if "[INSERT" in f.read():
                        left.append(os.path.relpath(p, ROOT))
    print("placeholders remaining:", left or "none")


if __name__ == "__main__":
    main()
