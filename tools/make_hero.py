#!/usr/bin/env python3
"""The AccessBench flagship visual: the open door.

A doorway with its door standing open. The door carries the data: records
down, fields across, some of them blacked out, under a lintel that names the
fields. An agent walks in on a solid line, which is the permission the
governance stack already grants. A dashed line reaches back at the records
and ends in an eye, which is the check that should be reading them field by
field. It is dashed because it is not there.

The agent and the eye are drawn to one scale, so that either would fit the
same square, and both are flat filled shapes in one weight, so they read as
parts of the same drawing as the door.

Outputs
  docs/assets/hero.svg        headline set, for the README and for a paper
  docs/assets/hero-plain.svg  no headline, for a page that sets its own type
  docs/assets/mark.svg        square mark, for a favicon or an app icon
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import head, tail, text, polygon, c, write  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "assets")

W, H = 860, 700

# ---------------------------------------------------------------- geometry --
# The doorway. A real door is about one wide to two tall; with the frame the
# whole thing sits near three to four. The frame is visible and plain.
JW, LH = 24.0, 30.0                 # jamb width, lintel height
IX0, IX1 = 282.0, 578.0             # opening, 296 wide
TOPY = 60.0
IY0, IY1 = TOPY + LH, 536.0         # opening, 446 tall
LX, RX = IX0 - JW, IX1 + JW         # frame outer edges, 344 wide

# The leaf hangs on the left jamb and stands open toward the viewer. The near
# edge is taller because it is closer.
FAR_X, FAR_Y0, FAR_H = IX0, IY0, IY1 - IY0
NEAR_X = IX0 + (IX1 - IX0) * 0.76
NEAR_H = FAR_H * 1.12
NEAR_Y0 = (IY0 + IY1) / 2 - NEAR_H / 2 - 4
SLAB = 9.0                          # the leaf seen edge on
GUT = 3.0                           # gutter between fields
STILE = 0.87                        # records stop here, rail beyond
CELL_R = 3.0                        # corner radius on a record cell

NCOL, NROW = 4, 10
MASKED_FIELD = 2                                   # one field masked
MASKED_ROWS = {0, 1, 3, 4, 6, 8, 9}                # ...on most records
WITHHELD_ROWS = {5}                                # a whole record withheld
SPOT = {(1, 0), (2, 3), (4, 1), (6, 0), (9, 3)}    # single values withheld

# The two actors share one square.
ICON = 80.0
AGENT_X, AGENT_Y = 170.0, 296.0     # centre of the agent's square
EYE_X, EYE_Y = 690.0, 404.0         # centre of the eye's square
FLOOR_Y = NEAR_Y0 + NEAR_H


def is_black(r, col):
    return ((col == MASKED_FIELD and r in MASKED_ROWS)
            or r in WITHHELD_ROWS or (r, col) in SPOT)


def gv(v):
    """Perspective across the leaf, hinge (0) to free edge (1)."""
    return (v * NEAR_H) / ((1 - v) * FAR_H + v * NEAR_H)


def ptg(g, t):
    fx, fy = FAR_X, FAR_Y0 + FAR_H * t
    nx, ny = NEAR_X, NEAR_Y0 + NEAR_H * t
    return fx + (nx - fx) * g, fy + (ny - fy) * g


def rounded_quad(pts, r, fill, stroke=None, sw=1.0, extra=""):
    """A four-sided cell with softened corners, drawn as a path so it survives
    the leaf's perspective."""
    n = len(pts)
    d = ""
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]

        def toward(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = (dx * dx + dy * dy) ** 0.5 or 1.0
            k = min(r, ln / 2)
            return a[0] + dx * k / ln, a[1] + dy * k / ln

        ax, ay = toward(p1, p0)
        bx, by = toward(p1, p2)
        d += (f"{'M' if i == 0 else 'L'}{ax:.1f} {ay:.1f} "
              f"Q{p1[0]:.1f} {p1[1]:.1f} {bx:.1f} {by:.1f} ")
    d += "Z"
    st = f";stroke:{c(stroke)};stroke-width:{sw}" if stroke else ""
    return f'<path d="{d}" style="fill:{c(fill)}{st}"{extra}/>\n'


# ------------------------------------------------------------------ pieces --
def interior():
    """The room behind the leaf, flat."""
    return polygon([(IX0, IY0), (IX1, IY0), (IX1, IY1), (IX0, IY1)], "room")


def frame():
    """Two jambs and a lintel. The lintel carries one tab per field, so the
    frame names the schema the door's records are cut into."""
    s = ""
    for x in (LX, IX1):
        s += (f'<rect x="{x:.1f}" y="{TOPY:.1f}" width="{JW:.1f}" '
              f'height="{IY1 - TOPY:.1f}" rx="2" style="fill:{c("framefill")};'
              f'stroke:{c("frameedge")};stroke-width:1.6"/>\n')
    s += (f'<rect x="{LX:.1f}" y="{TOPY:.1f}" width="{RX - LX:.1f}" '
          f'height="{LH:.1f}" rx="2" style="fill:{c("framefill")};'
          f'stroke:{c("frameedge")};stroke-width:1.6"/>\n')
    step = (IX1 - IX0) / NCOL
    for i in range(NCOL):
        x = IX0 + i * step
        w = step * 0.52
        s += (f'<rect x="{x + (step - w) / 2:.1f}" y="{TOPY + LH / 2 - 3:.1f}" '
              f'width="{w:.1f}" height="6" rx="3" '
              f'style="fill:{c("celllit")};opacity:0.55"/>\n')
    return s


def leaf():
    """The door: records down, fields across, some of them blacked out."""
    s = polygon([ptg(1, 0), (NEAR_X + SLAB, NEAR_Y0 + 5),
                 (NEAR_X + SLAB, NEAR_Y0 + NEAR_H + 5), ptg(1, 1)],
                "slab", "slabedge", 1.6)
    s += polygon([ptg(0, 0), ptg(1, 0), ptg(1, 1), ptg(0, 1)],
                 "face", "faceedge", 2.0)

    eps = (GUT / 2) / (NEAR_X - FAR_X)
    t0, gap = 0.04, 0.022
    band = (0.965 - t0 - gap * (NROW - 1)) / NROW
    for r in range(NROW):
        ta = t0 + r * (band + gap)
        tb = ta + band
        for col in range(NCOL):
            ga = STILE * gv(col / NCOL) + (eps if col else 2.2 * eps)
            gb = STILE * gv((col + 1) / NCOL) - (eps if col < NCOL - 1 else 0)
            pts = [ptg(ga, ta), ptg(gb, ta), ptg(gb, tb), ptg(ga, tb)]
            if is_black(r, col):
                s += rounded_quad(pts, CELL_R, "cellblack", "cellblkedge", 1.0)
            else:
                s += rounded_quad(pts, CELL_R, "celllit", None, 0,
                                  ' opacity="0.9"')

    s += (f'<line x1="{FAR_X:.1f}" y1="{FAR_Y0:.1f}" x2="{FAR_X:.1f}" '
          f'y2="{FAR_Y0 + FAR_H:.1f}" style="stroke:{c("hinge")};'
          f'stroke-width:2"/>\n')
    hx, hy = ptg(0.935, 0.5)
    s += (f'<rect x="{hx - 3.2:.1f}" y="{hy - 17:.1f}" width="6.4" height="34" '
          f'rx="3.2" style="fill:{c("handle")}"/>\n')
    return s


def agent(cx, cy, size=ICON):
    """A filled silhouette of a small agent: a body with rounded top corners
    and four legs underneath, centred. No face and no arms, so it stays a
    figure and never becomes a character."""
    u = size / 10.0
    bw, bh = 8 * u, 6 * u
    bx, by = cx - bw / 2, cy - 4 * u
    k = 1.0 * u
    s = (f'<path d="M{bx:.1f} {by + bh:.1f} V{by + k:.1f} '
         f'Q{bx:.1f} {by:.1f} {bx + k:.1f} {by:.1f} '
         f'H{bx + bw - k:.1f} Q{bx + bw:.1f} {by:.1f} {bx + bw:.1f} {by + k:.1f} '
         f'V{by + bh:.1f} Z" style="fill:{c("agent")}"/>\n')
    # four legs, one unit wide. The outer two sit flush with the body's
    # corners; the inner two split the span between them evenly.
    span = bw - u
    for i in range(4):
        lx = bx + span * i / 3
        s += (f'<rect x="{lx:.1f}" y="{by + bh - 0.5:.1f}" width="{u:.1f}" '
              f'height="{2 * u + 0.5:.1f}" style="fill:{c("agent")}"/>\n')
    return s


def eye(cx, cy, size=ICON):
    """A filled eye: one thick arc over a round pupil that sits up inside it.
    Circular, not stretched, and the same size as the agent."""
    ro = size / 2.0                       # outer radius of the lid
    sw = size * 0.19                      # the lid's thickness
    rc = ro - sw / 2                      # centreline radius
    pr = size * 0.21                      # pupil radius
    chord = cy + size * 0.10              # the lid's baseline
    s = (f'<path d="M{cx - rc:.1f} {chord:.1f} A{rc:.1f} {rc:.1f} 0 0 1 '
         f'{cx + rc:.1f} {chord:.1f}" fill="none" style="stroke:{c("brandred")};'
         f'stroke-width:{sw:.1f}"/>\n')
    s += (f'<circle cx="{cx:.1f}" cy="{chord + pr * 0.35:.1f}" r="{pr:.1f}" '
          f'style="fill:{c("brandred")}"/>\n')
    return s


def agent_line():
    """Solid, because this permission exists and is enforced today. One line
    from the agent, under the open leaf, across the opening and out past the
    far jamb: the agent went through."""
    y = AGENT_Y
    return (f'<line x1="{AGENT_X + ICON / 2 + 10:.1f}" y1="{y:.1f}" '
            f'x2="{RX + 40:.1f}" y2="{y:.1f}" style="stroke:{c("agent")};'
            f'stroke-width:2.6;stroke-linecap:round" '
            f'marker-end="url(#ah-agent)"/>\n')


def missing_check():
    """Dashed, because this check is not there. It mirrors the agent's line:
    from the eye, back across every record on the leaf, to the hinge side."""
    y = EYE_Y + ICON * 0.10 + ICON * 0.21 * 0.35   # level with the pupil
    return (f'<line x1="{EYE_X - ICON / 2 - 10:.1f}" y1="{y:.1f}" '
            f'x2="{IX0 + 14:.1f}" y2="{y:.1f}" style="stroke:{c("brandred")};'
            f'stroke-width:2.6;stroke-dasharray:11 9;stroke-linecap:round" '
            f'marker-end="url(#ah-brandred)"/>\n')


def floor():
    return (f'<line x1="{LX - 36:.1f}" y1="{FLOOR_Y + 6:.1f}" x2="{RX + 36:.1f}" '
            f'y2="{FLOOR_Y + 6:.1f}" style="stroke:{c("grid")};'
            f'stroke-width:1.6"/>\n')


def scene():
    return (interior() + frame() + agent_line() + leaf() + floor()
            + agent(AGENT_X, AGENT_Y) + missing_check() + eye(EYE_X, EYE_Y))


# ------------------------------------------------------------------ files --
def build_hero(with_headline=True):
    h = H if with_headline else 608
    s = head(W, h, "An agent walks through the app door and reaches every "
                   "record behind it, field by field, with nothing checking "
                   "which ones it was allowed to see")
    s += scene()
    if with_headline:
        s += text(430, 630,
                  "Current governance decides agent access across apps.",
                  size=27, weight=600, fill="ink", anchor="middle")
        s += text(430, 668,
                  "Nothing checks what data an agent accesses once inside.",
                  size=27, weight=600, fill="ink", anchor="middle")
    return s + tail()


def build_mark():
    """The same door, redrawn simple enough to survive a favicon."""
    S = 512
    jw, lh = 26.0, 30.0
    ix0, ix1 = 150.0, 362.0
    top = 58.0
    iy0, iy1 = top + lh, 454.0
    nx = ix0 + (ix1 - ix0) * 0.76
    fh = iy1 - iy0
    nh = fh * 1.10
    ny0 = (iy0 + iy1) / 2 - nh / 2
    nrow, ncol, stile = 6, 3, 0.86
    black = {(1, 1), (2, 1), (4, 1), (3, 0), (5, 2), (0, 2)}

    def g(v):
        return (v * nh) / ((1 - v) * fh + v * nh)

    def q(gg, t):
        fx, fy = ix0, iy0 + fh * t
        return fx + (nx - fx) * gg, fy + ((ny0 + nh * t) - fy) * gg

    s = head(S, S, "AccessBench mark")
    s += polygon([(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)], "room")
    for x in (ix0 - jw, ix1):
        s += (f'<rect x="{x:.1f}" y="{top:.1f}" width="{jw:.1f}" '
              f'height="{iy1 - top:.1f}" rx="2" style="fill:{c("framefill")};'
              f'stroke:{c("frameedge")};stroke-width:2.4"/>\n')
    s += (f'<rect x="{ix0 - jw:.1f}" y="{top:.1f}" '
          f'width="{ix1 - ix0 + 2 * jw:.1f}" height="{lh:.1f}" rx="2" '
          f'style="fill:{c("framefill")};stroke:{c("frameedge")};'
          f'stroke-width:2.4"/>\n')
    step = (ix1 - ix0) / ncol
    for i in range(ncol):
        w = step * 0.5
        s += (f'<rect x="{ix0 + i * step + (step - w) / 2:.1f}" '
              f'y="{top + lh / 2 - 4:.1f}" width="{w:.1f}" height="8" rx="4" '
              f'style="fill:{c("celllit")};opacity:0.55"/>\n')
    s += polygon([q(1, 0), (nx + 12, ny0 + 6), (nx + 12, ny0 + nh + 6), q(1, 1)],
                 "slab", "slabedge", 2.4)
    s += polygon([q(0, 0), q(1, 0), q(1, 1), q(0, 1)], "face", "faceedge", 3.0)
    eps = 2.4 / (nx - ix0)
    t0, gap = 0.05, 0.03
    band = (0.95 - t0 - gap * (nrow - 1)) / nrow
    for r in range(nrow):
        ta = t0 + r * (band + gap)
        tb = ta + band
        for col in range(ncol):
            ga = stile * g(col / ncol) + (eps if col else 2.2 * eps)
            gb = stile * g((col + 1) / ncol) - (eps if col < ncol - 1 else 0)
            pts = [q(ga, ta), q(gb, ta), q(gb, tb), q(ga, tb)]
            if (r, col) in black:
                s += rounded_quad(pts, 4.0, "cellblack", "cellblkedge", 1.8)
            else:
                s += rounded_quad(pts, 4.0, "celllit", None, 0, ' opacity="0.9"')
    hx, hy = q(0.935, 0.5)
    s += (f'<rect x="{hx - 3.6:.1f}" y="{hy - 17:.1f}" width="7.2" height="34" '
          f'rx="3.6" style="fill:{c("handle")}"/>\n')
    return s + tail()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write(os.path.join(OUT, "hero.svg"), build_hero(True))
    write(os.path.join(OUT, "hero-plain.svg"), build_hero(False))
    write(os.path.join(OUT, "mark.svg"), build_mark())
