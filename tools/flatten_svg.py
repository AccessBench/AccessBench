#!/usr/bin/env python3
"""Flatten the figures for tools that cannot read CSS custom properties.

The figures in docs/assets/ carry a light value and a dark value for every
colour and pick between them with a media query, which is what lets one file
sit correctly on a light or a dark page. Design tools import SVG as plain
geometry and drop the stylesheet, so they need a copy with the hex values
written in directly.

    python3 tools/flatten_svg.py --theme dark --out build/figma

Use it for Figma, Illustrator, Keynote, or anywhere the SVG is being edited by
hand rather than served to a reader. Never commit the output; the files in
docs/assets/ stay the source of truth.
"""

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import TOK  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flatten(svg, theme):
    idx = 0 if theme == "light" else 1
    svg = re.sub(r"<style>.*?</style>\n?", "", svg, flags=re.S)
    for name, pair in TOK.items():
        svg = svg.replace(f"var(--ab-{name})", pair[idx])
    left = re.findall(r"var\(--ab-[a-zA-Z0-9]+\)", svg)
    if left:
        raise SystemExit(f"unresolved tokens: {sorted(set(left))}")
    return svg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", choices=("light", "dark"), default="dark")
    ap.add_argument("--out", default="build/figma")
    ap.add_argument("--plate", action="store_true",
                    help="add a background rect, for a tool that shows no page")
    a = ap.parse_args()

    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    os.makedirs(out, exist_ok=True)
    plate = "#ffffff" if a.theme == "light" else "#0d1117"

    n = 0
    for src in sorted(glob.glob(os.path.join(ROOT, "docs", "assets", "*.svg"))):
        svg = flatten(open(src).read(), a.theme)
        if a.plate:
            m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
            w, h = m.group(1), m.group(2)
            svg = re.sub(r"(<title>.*?</title>\n)",
                         rf'\1<rect width="{w}" height="{h}" fill="{plate}"/>\n',
                         svg, count=1, flags=re.S)
        dst = os.path.join(out, os.path.basename(src))
        with open(dst, "w") as f:
            f.write(svg)
        n += 1
    print(f"wrote {n} {a.theme} files to {out}")


if __name__ == "__main__":
    main()
