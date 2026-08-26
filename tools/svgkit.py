"""Shared drawing kit for the AccessBench figures.

One palette, one type scale, one arrow vocabulary, so every figure in the
repository reads as the same system.

Two rules the figures live by:

1. No background. A figure paints its boxes and nothing else, so it sits on the
   page it is embedded in rather than on a card of its own.
2. Every colour is a token, and every token has a light value and a dark value.
   The values ride in a `<style>` block inside each file, so one SVG follows
   whichever theme the reader is in.

The dark values are the dashboard palette (`dashboard/static/styles.css`); the
variable names in that stylesheet are historical and the hex values are what
count. The light values are their counterparts, picked to keep the same
contrast against a light page.

Type is Charter throughout, the AccessBench face.
"""

from html import escape

# token: (light, dark)
TOK = {
    # type and rules
    "ink":         ("#14141a", "#f4f4f2"),
    "ink2":        ("#45454e", "#b9b9bd"),
    "muted":       ("#6b6b75", "#83838b"),
    "faint":       ("#8a8a93", "#6e6e77"),
    "grid":        ("#d5d5dc", "#2a2a2e"),
    "line":        ("#a0a0aa", "#4a4a52"),
    "arrowmuted":  ("#b0b0ba", "#5c5c65"),
    # box roles
    "panel":       ("#f7f7f9", "#16161a"),
    "panel2":      ("#f1f1f4", "#141418"),
    "inputbg":     ("#f4f4f7", "#141419"),
    "inputst":     ("#d2d2da", "#3a3a42"),
    "testbg":      ("#fcf1f4", "#1c1319"),
    "testst":      ("#d59cac", "#7d2038"),
    "passbg":      ("#f0f8f1", "#101a11"),
    "passst":      ("#9fcda3", "#245c28"),
    "sealedbg":    ("#e9e9ef", "#060607"),
    "sealedst":    ("#c4c4ce", "#2f2f36"),
    "outbg":       ("#f5f5f8", "#17171c"),
    "outst":       ("#bcbcc6", "#4a4a52"),
    # chips
    "chipbg":      ("#eeeef2", "#1d1d23"),
    "chipst":      ("#d5d5dd", "#3a3a44"),
    "chiptestbg":  ("#fbeef1", "#22141a"),
    "chippassbg":  ("#eef7ef", "#111b12"),
    "chipsealbg":  ("#e7e7ed", "#0b0b0d"),
    "chipsealst":  ("#c8c8d2", "#33333c"),
    # brand and status
    "scarlet":     ("#a02347", "#c9364f"),
    "brandtx":     ("#8f1f3f", "#e3899a"),
    "good":        ("#128012", "#0ca30c"),
    "goodtx":      ("#14761a", "#5fbf5f"),
    # figure furniture
    "ctrlbar":     ("#9a9aa4", "#8a8a93"),
    "stackbg":     ("#eeeef2", "#1d1d23"),
    "stackst":     ("#ccccd6", "#3f3f4a"),
    "gridread":    ("#c6c6ce", "#3d3d47"),
    "gridegress":  ("#8e8e9a", "#7d7d8b"),
    # the door and the two actors in the hero
    "agent":       ("#1f7a4d", "#34a06a"),
    "brandred":    ("#c9364f", "#c9364f"),   # the AccessBench scarlet, both themes
    "room":        ("#1b1b21", "#08080c"),
    "face":        ("#e6e6eb", "#2c2c36"),
    "faceedge":    ("#b9b9c4", "#5a5a67"),
    "celllit":     ("#9a9aa6", "#dcdce0"),
    "cellblack":   ("#0f0f13", "#08080a"),
    "cellblkedge": ("#5a5a66", "#4d4d59"),
    "framefill":   ("#dcdce3", "#262630"),
    "frameedge":   ("#aeaeba", "#3e3e4a"),
    "slab":        ("#d4d4dc", "#2b2b33"),
    "slabedge":    ("#a8a8b4", "#4a4a56"),
    "rail":        ("#dcdce3", "#33333d"),
    "hinge":       ("#9a9aa6", "#5b5b66"),
    "handle":      ("#7a7a86", "#b9b9bd"),
    "roomA":       ("#15151b", "#050506"),
    "roomB":       ("#24242c", "#0c0c10"),
    "roomC":       ("#35353f", "#17171d"),
    "reveal":      ("#44444f", "#24242c"),
}

# Charter is the AccessBench face everywhere, in the docs and in the product.
SERIF = ("Charter, 'Charter BT', 'Bitstream Charter', 'Charis SIL', "
         "ui-serif, Georgia, serif")
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

# Box roles: fill token, stroke token, corner-dot token.
ROLE = {
    "plain":  ("panel",    "grid",     None),
    "input":  ("inputbg",  "inputst",  None),
    "test":   ("testbg",   "testst",   "scarlet"),
    "pass":   ("passbg",   "passst",   "good"),
    "sealed": ("sealedbg", "sealedst", None),
    "out":    ("outbg",    "outst",    None),
}

ARROW_TOK = {"ink": "line", "scarlet": "scarlet", "good": "good",
             "agent": "agent", "brandred": "brandred", "muted": "arrowmuted",
             "ink2": "ink2"}


def c(tok):
    """A token reference, or a literal if it is already one."""
    if tok in (None, "none"):
        return "none"
    if tok.startswith("#") or tok.startswith("url("):
        return tok
    return f"var(--ab-{tok})"


def style_block():
    light = "".join(f"--ab-{k}:{v[0]};" for k, v in TOK.items())
    dark = "".join(f"--ab-{k}:{v[1]};" for k, v in TOK.items())
    return ("<style>\n"
            f":root{{{light}}}\n"
            f"@media (prefers-color-scheme:dark){{:root{{{dark}}}}}\n"
            "</style>\n")


def defs():
    out = ['<defs>',
           '<linearGradient id="brandgrad" x1="0" y1="0" x2="1" y2="1">',
           f'<stop offset="0" stop-color="{c("scarlet")}"/>',
           f'<stop offset="1" stop-color="{c("brandtx")}"/>',
           '</linearGradient>']
    for name, tok in ARROW_TOK.items():
        out.append(
            f'<marker id="ah-{name}" viewBox="0 0 10 10" refX="8.6" refY="5" '
            f'markerWidth="6.4" markerHeight="6.4" orient="auto-start-reverse">'
            f'<path d="M0 0.7 L9.6 5 L0 9.3 Z" style="fill:{c(tok)}"/></marker>')
    out.append('</defs>')
    return "".join(out) + "\n"


def head(w, h, title):
    """No background rect. The figure sits on whatever page embeds it."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" aria-label="{escape(title)}">\n'
            f'<title>{escape(title)}</title>\n' + style_block() + defs())


def tail():
    return "</svg>\n"


def rect(x, y, w, h, fill, stroke, rx=8, sw=1, extra=""):
    st = f";stroke:{c(stroke)};stroke-width:{sw}" if stroke not in (None, "none") else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" style="fill:{c(fill)}{st}"{extra}/>\n')


def text(x, y, s, size=14, fill="ink", family=None, weight=400, anchor="start",
         ls=0, opacity=1):
    op = f';opacity:{opacity}' if opacity != 1 else ""
    lsa = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family or SERIF}" '
            f'font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{lsa} style="fill:{c(fill)}{op}">'
            f'{escape(s)}</text>\n')


def box(x, y, w, h, title, sub=None, role="plain", code=None, tsize=14.5,
        ssize=11.2, anchor="middle", rx=8):
    """A labelled box: a name, an optional plain-English half sentence, an
    optional mono identifier."""
    fill, stroke, dot = ROLE[role]
    out = rect(x, y, w, h, fill, stroke, rx=rx)
    tx = x + w / 2 if anchor == "middle" else x + 13
    lines = [l for l in (sub, code) if l]
    ty = y + h / 2 + tsize * 0.34 - (len(lines) * 7.4)
    out += text(tx, ty, title, size=tsize, weight=600, anchor=anchor)
    cy = ty
    if sub:
        cy += 15.0
        out += text(tx, cy, sub, size=ssize, fill="muted", anchor=anchor)
    if code:
        cy += 14.2
        out += text(tx, cy, code, size=10.2, fill="ink2", family=MONO,
                    anchor=anchor)
    if dot:
        out += (f'<circle cx="{x + w - 11:.1f}" cy="{y + 11:.1f}" r="3" '
                f'style="fill:{c(dot)}"/>\n')
    return out


def line(x1, y1, x2, y2, kind="ink", dash=None, sw=1.5, head_=True):
    da = f";stroke-dasharray:{dash}" if dash else ""
    mk = f' marker-end="url(#ah-{kind})"' if head_ else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'style="stroke:{c(ARROW_TOK[kind])};stroke-width:{sw}{da};'
            f'stroke-linecap:round"{mk}/>\n')


def arrow(x1, y1, x2, y2, kind="ink", dash=None, sw=1.5, label=None,
          lsize=10.2, lpos=0.5, ldy=-8, lfill="muted", family=None, head_=True):
    out = line(x1, y1, x2, y2, kind, dash, sw, head_)
    if label:
        out += text(x1 + (x2 - x1) * lpos, y1 + (y2 - y1) * lpos + ldy, label,
                    size=lsize, fill=lfill, family=family or MONO,
                    anchor="middle")
    return out


def elbow(pts, kind="ink", dash=None, sw=1.5, r=10, head_=True):
    """Orthogonal polyline with rounded corners."""
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(1, len(pts) - 1):
        (px, py), (cx, cy), (nx, ny) = pts[i - 1], pts[i], pts[i + 1]

        def trim(ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            ln = (dx * dx + dy * dy) ** 0.5 or 1.0
            k = min(r, ln / 2)
            return ax + dx * k / ln, ay + dy * k / ln

        ix, iy = trim(cx, cy, px, py)
        ox, oy = trim(cx, cy, nx, ny)
        d += f" L{ix:.1f} {iy:.1f} Q{cx:.1f} {cy:.1f} {ox:.1f} {oy:.1f}"
    d += f" L{pts[-1][0]:.1f} {pts[-1][1]:.1f}"
    da = f";stroke-dasharray:{dash}" if dash else ""
    mk = f' marker-end="url(#ah-{kind})"' if head_ else ""
    return (f'<path d="{d}" fill="none" style="stroke:{c(ARROW_TOK[kind])};'
            f'stroke-width:{sw}{da};stroke-linecap:round"{mk}/>\n')


def polygon(points, fill, stroke=None, sw=1.0, extra=""):
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    st = f";stroke:{c(stroke)};stroke-width:{sw}" if stroke else ""
    return f'<polygon points="{d}" style="fill:{c(fill)}{st}"{extra}/>\n'


def caption(x, y, s, size=11.4, anchor="start", fill="muted"):
    return text(x, y, s, size=size, fill=fill, anchor=anchor)


def figtitle(x, y, s, sub=None):
    out = text(x, y, s, size=15.5, weight=600, ls=0.2)
    if sub:
        out += text(x, y + 17, sub, size=11.4, fill="muted")
    return out


def hairline(x, y, w=48, h=2.5):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" '
            f'fill="url(#brandgrad)"/>\n')


def write(path, s):
    with open(path, "w") as f:
        f.write(s)
    print("wrote", path, len(s), "bytes")
