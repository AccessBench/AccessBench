#!/usr/bin/env python3
"""The figures that sit inside the AccessBench documents.

Every figure is drawn from the same kit so the set reads as one system. Boxes
carry a name and at most one short line of plain English. Anything longer
belongs in the paragraph the figure sits next to.

Run: python3 tools/make_diagrams.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import (SERIF, MONO, head, tail, rect, text, box, arrow, line,  # noqa: E402
                    elbow, caption, figtitle, hairline, c, write)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "assets")


# ------------------------------------------------------------------ extras --
CHIP = {
    "plain":  ("chipbg",     "chipst",     "ink2"),
    "test":   ("chiptestbg", "testst",     "brandtx"),
    "pass":   ("chippassbg", "passst",     "goodtx"),
    "sealed": ("chipsealbg", "chipsealst", "muted"),
}


def chip(x, y, label, tone="plain", size=10.6, family=None, pad=9, h=22):
    """A small pill. Returns (svg, width)."""
    family = family or MONO
    w = pad * 2 + len(label) * (size * 0.6 if family == MONO else size * 0.52)
    fill, stroke, fg = CHIP[tone]
    s = rect(x, y, w, h, fill, stroke, rx=h / 2)
    s += text(x + w / 2, y + h / 2 + size * 0.36, label, size=size, fill=fg,
              family=family, anchor="middle")
    return s, w


def chiprow(x, y, labels, tone="plain", gap=8, **kw):
    s, cx = "", x
    for lb in labels:
        piece, w = chip(cx, y, lb, tone=tone, **kw)
        s += piece
        cx += w + gap
    return s, cx - x - gap


def barpair(x, y, w, h, a, b, la="control", lb="enforced"):
    """Two paired bars. Grey is the control arm, scarlet the layer under test."""
    bw = (w - 18) / 2
    s = ""
    for i, (frac, tok, lab) in enumerate(((a, "ctrlbar", la),
                                          (b, "scarlet", lb))):
        bh = max(4.0, h * frac)
        bx = x + i * (bw + 18)
        s += rect(bx, y + h - bh, bw, bh, tok, None, rx=3)
        s += text(bx + bw / 2, y + h + 15, lab, size=9.6, fill="muted",
                  family=MONO, anchor="middle")
    return s


def stack(x, y, w, h, n=4, off=7):
    """Offset rectangles, for 'the same thing in n variations'."""
    s = ""
    for i in range(n - 1, -1, -1):
        s += rect(x + i * off, y + i * off, w, h, "stackbg", "stackst", rx=6)
    return s


def vlabel(x, y, s_, size=11, fill="muted"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SERIF}" '
            f'font-size="{size}" style="fill:{c(fill)}" text-anchor="middle" '
            f'transform="rotate(-90 {x:.1f} {y:.1f})">{s_}</text>\n')


# ----------------------------------------------------------------- figures --
def fig_run():
    """README: two inputs, the same cases run twice, one signed file."""
    W, H = 900, 268
    s = head(W, H, "Two inputs enter the harness, the same 600 cases run twice, "
                   "one signed results file comes out")
    s += hairline(40, 30)
    s += figtitle(40, 58, "One run, end to end")

    s += box(40, 92, 172, 62, "Model", "any chat endpoint", role="input")
    s += box(40, 168, 172, 62, "Enforcement", "the layer under test", role="test")
    s += arrow(212, 123, 292, 143)
    s += arrow(212, 199, 292, 179)

    s += rect(300, 86, 300, 150, "panel2", "grid")
    s += text(316, 110, "AccessBench", size=14.5, weight=600)
    s += text(316, 127, "600 fixed cases, run once per arm", size=10.8,
              fill="muted")
    s += rect(316, 142, 268, 36, "chipbg", "chipst", rx=6)
    s += text(330, 164, "no enforcement", size=11, fill="ink2", family=MONO)
    s += text(570, 164, "control", size=10, fill="muted", family=MONO,
              anchor="end")
    s += rect(316, 186, 268, 36, "chiptestbg", "testst", rx=6)
    s += text(330, 208, "enforcement on", size=11, fill="brandtx", family=MONO)
    s += text(570, 208, "under test", size=10, fill="muted", family=MONO,
              anchor="end")

    s += arrow(600, 161, 686, 161)
    s += box(694, 118, 168, 86, "Signed result", "one file, percent first",
             role="out", code="summary.json")
    s += caption(40, 254, "The pair is the point. A single number with nothing "
                          "to compare it against is not a result.")
    return s + tail()


def fig_paired():
    """01-design: one bank, two arms, one grader, two bars."""
    W, H = 900, 330
    s = head(W, H, "One fixed bank feeds two arms, the same grader scores both, "
                   "the result is a pair of percentages")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The paired experiment",
                  "Everything is held still except the enforcement layer.")

    s += box(40, 148, 172, 92, "600 fixed cases", "same bank, same order",
             code="core_v2.jsonl")
    s += elbow([(212, 172), (244, 172), (244, 130), (278, 130)])
    s += elbow([(212, 216), (244, 216), (244, 258), (278, 258)])

    s += box(286, 96, 244, 68, "Agent alone", "no enforcement layer at all")
    s += box(286, 224, 244, 68, "Agent plus enforcement", "same model, same cases",
             role="test")

    s += elbow([(530, 130), (562, 130), (562, 172), (594, 172)])
    s += elbow([(530, 258), (562, 258), (562, 216), (594, 216)])
    s += box(602, 148, 148, 92, "One grader", "same answer key both arms")

    s += arrow(750, 194, 780, 194)
    s += barpair(790, 150, 84, 76, 0.86, 0.18)
    s += caption(40, 312, "Same agent, same cases, one difference. The gap "
                          "between the two bars is the whole measurement.")
    return s + tail()


def fig_lifecycle():
    """01-design: one case, from the request to the grade."""
    W, H = 900, 314
    s = head(W, H, "One case runs from the request and its world through the "
                   "agent's tool action and the enforcement decision to the "
                   "grader")
    s += hairline(40, 30)
    s += figtitle(40, 58, "How one case runs",
                  "The enforcement layer answers one event at a time. "
                  "Everything else is fixed machinery.")

    s += box(380, 108, 200, 60, "Enforcement", "allow, deny, or rewrite",
             role="test")

    y, h = 194, 74
    specs = [(40, 166, "Request and world", "the task, and the data behind it"),
             (224, 156, "Agent picks a move", "one tool action"),
             (398, 146, "Boundary event", "a read or an egress"),
             (562, 146, "App commits", "only what came back allowed"),
             (726, 146, "Grader", "task done, nothing leaked")]
    for x, w, t, sub in specs:
        s += box(x, y, w, h, t, sub)
    for i in range(4):
        x0 = specs[i][0] + specs[i][1]
        s += arrow(x0, y + h / 2, specs[i + 1][0] - 6, y + h / 2)

    s += arrow(452, y, 452, 174, sw=1.6)
    s += arrow(508, 170, 508, y - 4, sw=1.6)
    s += text(524, 186, "the answer comes back", size=10, fill="muted")

    s += caption(40, 296, "The grader checks two things at once: whether the "
                          "work got done, and whether a protected value left.")
    return s + tail()


def fig_seam():
    """02-methodology: what the enforcement layer can see, and what it cannot."""
    W, H = 900, 462
    s = head(W, H, "The enforcement layer sees the request and its context; "
                   "only the grader holds the planted values and the answer key")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The enforcement seam",
                  "Where the decision gets made, and on how little.")

    y = 100
    s += box(40, y, 118, 62, "Agent", "does the work")
    s += arrow(158, y + 31, 194, y + 31)
    s += box(202, y, 138, 62, "Boundary event", "read or egress")
    s += arrow(340, y + 31, 376, y + 31)
    s += box(384, y, 172, 62, "Enforcement", "allow, deny, or rewrite",
             role="test")
    s += arrow(556, y + 31, 592, y + 31)
    s += box(600, y, 138, 62, "Sandbox", "commits what was allowed")
    s += arrow(738, y + 31, 774, y + 31)
    s += box(782, y, 78, 62, "Grader")

    s += rect(40, 200, 396, 196, "panel2", "grid")
    s += text(58, 226, "What it sees", size=13.5, weight=600)
    s += text(58, 243, "everything on the request, and what the catalog says "
                       "about the record", size=10.6, fill="muted")
    for i, row in enumerate((["boundary", "app", "action", "resource"],
                             ["payload", "destination", "destination tenant"],
                             ["subject", "requester", "purpose", "approvals"],
                             ["observed labels", "record selector"],
                             ["source tenant", "requires approval"])):
        s += chiprow(58, 256 + i * 28, row, h=21, size=10)[0]

    s += rect(464, 200, 396, 196, "sealedbg", "sealedst")
    s += text(482, 226, "What only the grader holds", size=13.5, weight=600)
    s += text(482, 243, "never on the wire, never inferable from the event",
              size=10.6, fill="muted")
    for i, row in enumerate((["the planted values"], ["lineage"],
                             ["the answer key"], ["the expected outcome"])):
        s += chiprow(482, 262 + i * 31, row, tone="sealed", h=22, size=10.4)[0]

    s += line(450, 196, 450, 400, kind="scarlet", dash="6 6", sw=1.8, head_=False)
    s += text(450, 416, "the gap between these two columns is the problem",
              size=11, fill="brandtx", anchor="middle")
    s += caption(40, 446, "A rewrite may remove or mask. It may never add. "
                          "Ambiguity resolves on the permissive side, on purpose.")
    return s + tail()


def fig_result():
    """03-scope: what one run hands back."""
    W, H = 900, 356
    s = head(W, H, "One run returns one signed file holding a score section and "
                   "a separate integrity section")
    s += hairline(40, 30)
    s += figtitle(40, 58, "What one run hands back")

    s += box(40, 100, 160, 58, "Model", role="input")
    s += box(40, 172, 160, 58, "Enforcement", "the layer under test", role="test")
    s += box(40, 244, 160, 58, "none", "the control, always run", code="built in")
    s += elbow([(200, 129), (232, 129), (232, 201), (262, 201)])
    s += arrow(200, 201, 262, 201)
    s += elbow([(200, 273), (232, 273), (232, 201), (262, 201)])

    s += box(270, 166, 150, 70, "One run", "1,200 episodes")
    s += arrow(420, 201, 466, 201)

    s += rect(474, 96, 250, 210, "panel2", "grid")
    s += text(492, 122, "One signed file", size=14, weight=600)
    s += text(492, 139, "the runner can verify it locally", size=10.5,
              fill="muted")
    s += rect(492, 152, 214, 62, "chipbg", "chipst", rx=6)
    s += text(506, 174, "Score", size=12.5, weight=600)
    s += text(506, 190, "percent first, counts underneath", size=10, fill="muted")
    s += rect(492, 224, 214, 62, "chiptestbg", "testst", rx=6)
    s += text(506, 246, "Anti-Cheat", size=12.5, weight=600)
    s += text(506, 262, "status, evidence, reason codes", size=10, fill="muted")

    s += arrow(724, 255, 762, 255)
    for i, (lab, tone) in enumerate((("Valid", "pass"), ("Flagged", "plain"),
                                     ("Ineligible", "test"))):
        s += chip(766, 200 + i * 30, lab, tone=tone, size=10.6)[0]
    s += caption(40, 336, "No integrity state ever changes the score. The two "
                          "sections are read separately and reported together.")
    return s + tail()


def fig_integrity():
    """06-integrity: the two things a run produces, and where they meet."""
    W, H = 900, 338
    s = head(W, H, "Benchmark execution forks into the deterministic score and "
                   "the integrity check, and the two meet in one signed result")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The integrity decision",
                  "Two separate authorities, one file.")

    s += box(40, 148, 158, 76, "Two inputs", "model and enforcement",
             role="input")
    s += arrow(198, 186, 232, 186)
    s += box(240, 148, 170, 76, "Execution", "600 cases, both arms")

    s += elbow([(410, 172), (436, 172), (436, 110), (462, 110)])
    s += elbow([(410, 200), (436, 200), (436, 262), (462, 262)])
    s += box(470, 76, 214, 68, "Deterministic grader", "the performance score")
    s += box(470, 228, 214, 68, "Anti-Cheat", "status, evidence, reason codes",
             role="test")

    s += elbow([(684, 110), (708, 110), (708, 172), (722, 172)])
    s += elbow([(684, 262), (708, 262), (708, 200), (722, 200)])
    s += box(730, 148, 130, 76, "One signed", "result", tsize=13.5, role="out")

    s += caption(40, 320, "Anti-Cheat can stop a result being published. It can "
                          "never move the score. The grader keeps that.")
    return s + tail()


def fig_bank():
    """03-scope: the shape of the 600-case bank."""
    W, H = 900, 372
    s = head(W, H, "Twenty five leak types by six workflows makes 150 workflows; "
                   "four request surfaces each makes 600 cases")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The shape of the bank",
                  "Diversity comes from the workflows. The surfaces are a "
                  "controlled axis.")

    gx, gy, cw, ch, gap = 78, 126, 13.0, 17.0, 3.4
    ncols, nrows = 25, 6
    for col in range(ncols):
        for r in range(nrows):
            tok = "gridread" if col < 15 else "gridegress"
            s += rect(gx + col * (cw + gap), gy + r * (ch + gap), cw, ch, tok,
                      None, rx=2.5)
    gw = ncols * (cw + gap) - gap
    gh = nrows * (ch + gap) - gap
    s += rect(gx - 11, gy - 11, gw + 22, gh + 22, "none", "scarlet", rx=8)
    s += text(gx + gw / 2, gy - 21, "150 workflows, independently grounded",
              size=11.4, fill="brandtx", anchor="middle")

    s += vlabel(gx - 28, gy + gh / 2, "6 workflows")
    split = gx + 15 * (cw + gap) - gap / 2
    s += line(split, gy + gh + 16, split, gy + gh + 46, kind="muted", sw=1,
              head_=False)
    s += text((gx + split) / 2, gy + gh + 34, "15 bind on read", size=10.4,
              fill="faint", family=MONO, anchor="middle")
    s += text((split + gx + gw) / 2, gy + gh + 34, "10 bind on egress",
              size=10.4, fill="ink2", family=MONO, anchor="middle")
    s += text(gx + gw / 2, gy + gh + 56, "25 leak types", size=11.4,
              fill="muted", anchor="middle")

    s += arrow(gx + gw + 26, gy + gh / 2, gx + gw + 74, gy + gh / 2)
    sx = gx + gw + 86
    s += stack(sx, gy + 6, 96, 74, n=4)
    s += text(sx + 62, gy + gh + 34, "4 request surfaces", size=11.4,
              fill="muted", anchor="middle")
    s += text(sx + 62, gy + gh + 56, "same work, asked four ways", size=10.4,
              fill="faint", anchor="middle")

    s += text(40, 322, "= 600 scored cases", size=15.5, weight=600)
    s += caption(210, 322, "300 allowed and 300 forbidden, 24 cases per leak type.")
    return s + tail()


def fig_bricks():
    """02-methodology: the same method run on a real lakehouse."""
    W, H = 900, 336
    s = head(W, H, "One agent and one task set run under a broad grant and "
                   "under a governed identity against the same warehouse")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The method on a real lakehouse",
                  "Same construction, real grants, real row filters and column "
                  "masks.")

    s += box(40, 152, 158, 84, "Agent and tasks", "36 tasks, 3 repeats",
             code="8 leak types")
    s += elbow([(198, 176), (228, 176), (228, 128), (258, 128)])
    s += elbow([(198, 212), (228, 212), (228, 258), (258, 258)])

    s += box(266, 98, 216, 62, "Broad grant", "sees the whole warehouse")
    s += box(266, 228, 216, 62, "Governed identity", "scoped to the analyst role",
             role="test")

    s += elbow([(482, 128), (506, 128), (506, 172), (528, 172)])
    s += elbow([(482, 258), (506, 258), (506, 216), (528, 216)])

    s += rect(536, 132, 170, 124, "panel2", "grid")
    s += text(621, 158, "One warehouse", size=13.5, weight=600, anchor="middle")
    s += text(621, 174, "Unity Catalog, live SQL", size=10.4, fill="muted",
              anchor="middle")
    for i, lab in enumerate(("orders", "taxi trips", "retail facts")):
        s += chip(554, 186 + i * 24, lab, size=9.8)[0]

    s += arrow(706, 194, 726, 194)
    s += box(734, 160, 126, 68, "Egress", "did a planted value leave",
             role="pass", tsize=13, ssize=10.2)
    s += caption(40, 316, "Canaries are added through enrichment tables and "
                          "appended rows. The raw data is never edited.")
    return s + tail()


def fig_setup():
    """04-setup: three ways in, one pipeline out."""
    W, H = 900, 424
    s = head(W, H, "Three ways to run, one shared pipeline from raw events to "
                   "the dashboard")
    s += hairline(40, 30)
    s += figtitle(40, 58, "Three ways in, one pipeline out")

    s += box(40, 96, 196, 62, "1  Offline", "no model, no spend", role="pass")
    s += box(40, 174, 196, 62, "2  Hosted model", "an API key and an approval",
             role="input")
    s += box(40, 252, 196, 62, "3  Self-hosted", "your own GPU box", role="input")

    s += elbow([(236, 127), (276, 127), (276, 108), (322, 108)])
    s += box(330, 76, 214, 64, "Grader proof", "runs the whole seam, no model",
             role="pass")
    s += elbow([(236, 205), (286, 205), (286, 214), (330, 214)])
    s += elbow([(236, 283), (286, 283), (286, 214), (330, 214)])
    s += box(338, 180, 206, 68, "Run the eval", "the only run interface",
             code="eval/run_eval.py")

    s += elbow([(544, 214), (612, 214), (612, 332), (133, 332), (133, 352)],
               r=14)
    y2 = 356
    s += box(40, y2, 186, 62, "Raw events", "one line per episode",
             code="results_raw/")
    s += arrow(226, y2 + 31, 262, y2 + 31)
    s += box(270, y2, 186, 62, "Aggregate", "deterministic, rerunnable",
             code="eval/aggregate.py")
    s += arrow(456, y2 + 31, 492, y2 + 31)
    s += box(500, y2, 166, 62, "Summary", "the numbers of record", code="results/")
    s += arrow(666, y2 + 31, 702, y2 + 31)
    s += box(710, y2, 150, 62, "Dashboard", "reads runs, runs nothing")
    return s + tail()


def fig_sealed():
    """06-integrity: the life of a sealed pack."""
    W, H = 900, 396
    s = head(W, H, "The panel is selected, padded, encrypted per record, "
                   "scheduled by opaque handle, and verified at aggregation")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The life of a sealed pack",
                  "The runner does the work without learning which case it is "
                  "doing.")

    y = 100
    xs, ws = [40, 250, 460, 670], [190, 190, 190, 190]
    specs = [("Select the panel", "the exact 600 cases", "plain"),
             ("Shuffle and pad", "every record to 64 KiB", "plain"),
             ("Encrypt per record", "its own nonce and seal", "sealed"),
             ("Schedule by handle", "the runner sees a number", "sealed")]
    for x, w, (t, sub, role) in zip(xs, ws, specs):
        s += box(x, y, w, 72, t, sub, role=role)
    for i in range(3):
        s += arrow(xs[i] + ws[i], y + 36, xs[i + 1] - 10, y + 36)

    s += line(555, 172, 555, 196, kind="muted", dash="4 4", sw=1.3, head_=False)
    s += rect(390, 198, 330, 46, "sealedbg", "sealedst", rx=7)
    s += text(405, 218, "the plaintext index carries only", size=10.4,
              fill="muted")
    s += chiprow(405, 224, ["handle", "offset", "length", "nonce"],
                 tone="sealed", h=19, size=9.4, pad=7)[0]

    s += rect(40, 266, 820, 92, "passbg", "passst")
    s += text(58, 292, "Verified at aggregation", size=13.5, weight=600)
    s += text(842, 292, "all four, or the run does not count", size=10.6,
              fill="muted", anchor="end")
    s += chiprow(58, 306, ["signed run matches the sealed digest",
                           "every handle used exactly once"],
                 tone="pass", h=22, size=10, family=SERIF)[0]
    s += chiprow(58, 332, ["each handle resolves to one case",
                           "answer key replayed from a separate copy"],
                 tone="pass", h=22, size=10, family=SERIF)[0]

    s += caption(40, 382, "Sealing removes the assignment leak. On its own it "
                          "is not a security boundary.")
    return s + tail()


def fig_gates():
    """07-validation: everything a result passes before it may be published."""
    W, H = 900, 440
    s = head(W, H, "A run passes every gate in order before it is eligible for "
                   "publication")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The gates a result has to clear",
                  "In order. Any one of them failing ends the run's claim.")

    r1 = [("Signed first", "config and code, before inference"),
          ("Deterministic", "tests green, panel rebuilds exactly"),
          ("Split release", "private bank regenerated and compared"),
          ("Evidence", "every episode once, chain intact")]
    r2 = [("Identity", "signer in an independent registry"),
          ("Anti-Cheat", "Valid, Flagged, or Ineligible"),
          ("Isolation", "throwaway box, network denied"),
          ("Spend", "a hosted run needs an explicit yes")]

    bw, gap = 195, 15
    for i, (t, sub) in enumerate(r1):
        s += box(40 + i * (bw + gap), 100, bw, 74, t, sub)
        if i < 3:
            s += arrow(40 + i * (bw + gap) + bw, 137,
                       40 + (i + 1) * (bw + gap) - 5, 137)
    s += elbow([(835, 174), (862, 174), (862, 200), (28, 200), (28, 226),
                (36, 226)], r=13)
    for i, (t, sub) in enumerate(r2):
        role = "test" if t == "Anti-Cheat" else "plain"
        s += box(40 + i * (bw + gap), 226, bw, 74, t, sub, role=role)
        if i < 3:
            s += arrow(40 + i * (bw + gap) + bw, 263,
                       40 + (i + 1) * (bw + gap) - 5, 263)

    s += elbow([(835, 300), (862, 300), (862, 326), (450, 326), (450, 344)],
               r=13)
    s += box(280, 350, 340, 62, "Publication eligible", role="pass")
    s += text(640, 372, "core-v2 can never set this.", size=11, fill="brandtx")
    s += text(640, 389, "No admitted sealed pack exists yet.", size=11,
              fill="muted")
    return s + tail()


def fig_digests():
    """10-replication: every step bound to the one before it by a digest."""
    W, H = 820, 704
    s = head(W, H, "Each build step is bound to the one before it by a named "
                   "digest, from the reviewed prompt ledger to the summary")
    s += hairline(40, 30)
    s += figtitle(40, 58, "What binds a number to its source",
                  "Follow it in either direction. A digest matches or it does "
                  "not.")

    nodes = [("Reviewed prompt ledger", "human review, one line per prompt",
              "prompt_bank_human_review_v1.jsonl", "plain"),
             ("Prompt module", "the prompts the run actually used",
              "core_prompt_bank_v1.py", "plain"),
             ("Core catalog", "600 admitted cases", "catalog/core_v2.jsonl",
              "plain"),
             ("Panel", "the fixed set and its order",
              "accessbench-core-v2-development-600", "plain"),
             ("Run manifest", "what ran, and on which code", ".manifest.json",
              "plain"),
             ("Raw events", "one signed chain, head included",
              "results_raw/*.jsonl", "plain"),
             ("Summary", "the numbers of record", "results/<run>/summary.json",
              "pass")]
    links = ["prompt_set_sha256", "catalog_sha256", "trial_ids_sha256",
             "runtime_code.commitment", "raw_sha256", "rerun aggregate.py"]

    x, w, bh, step, y = 40, 348, 62, 78, 104
    for i, (t, sub, code, role) in enumerate(nodes):
        s += box(x, y + i * step, w, bh, t, sub, role=role, code=code,
                 anchor="start")
        if i < len(nodes) - 1:
            ay = y + i * step + bh
            s += line(x + 44, ay, x + 44, ay + step - bh - 2, kind="ink", sw=1.6)
            s += text(x + 58, ay + 12, links[i], size=10.4, fill="ink2",
                      family=MONO)

    s += box(540, 260, 240, 62, "Generation matrix", "10,800 rows",
             code="source_generation_matrix", tsize=13, anchor="start")
    s += arrow(540, 291, 398, 291)

    s += caption(40, 680, "A reproduction succeeds when the digest matches. "
                          "There is no close enough.")
    return s + tail()


def fig_headline():
    """README: the one figure a reader should see before anything else.

    Two measures, one pair of bars each. Grey is the agent with no enforcement
    layer, scarlet is the agent behind the Benchmark PDP. Every bar carries its
    own number, so the colour is never the only thing saying which is which.
    """
    W, H = 900, 392
    s = head(W, H, "Two paired bars: with the Benchmark PDP the agent completes "
                   "more work safely and exfiltrates far less protected data "
                   "than the same agent with no enforcement layer")
    s += hairline(40, 30)
    s += figtitle(40, 58, "What the enforcement layer changes",
                  "One model, one fixed bank, two arms. gpt-4o, 600 cases, "
                  "one pass each arm.")

    base = 316          # baseline the bars stand on
    full = 156          # pixels at 100 percent
    bw = 88             # bar width
    gap = 34

    groups = (
        (96, "Work completed safely", "share of all 600 cases",
         (54.2, "325 of 600"), (80.7, "484 of 600")),
        (516, "Protected data exfiltrated", "share of the 300 forbidden cases",
         (75.7, "227 of 300"), (5.0, "15 of 300")),
    )
    arms = ("no enforcement", "Benchmark PDP")

    for gx, title, sub, ctrl, test in groups:
        s += text(gx, 118, title, size=15, fill="ink", weight=700)
        s += text(gx, 137, sub, size=11.4, fill="muted", family=MONO)
        s += rect(gx, base, bw * 2 + gap, 1.5, "grid", None, rx=0)
        for i, ((pct, count), tok) in enumerate(zip((ctrl, test),
                                                    ("ctrlbar", "scarlet"))):
            bh = max(4.0, full * pct / 100.0)
            bx = gx + i * (bw + gap)
            by = base - bh
            s += rect(bx, by, bw, bh, tok, None, rx=3)
            s += text(bx + bw / 2, by - 26, f"{pct:.1f}%", size=21, fill="ink",
                      family=MONO, anchor="middle")
            s += text(bx + bw / 2, by - 11, count, size=10.4, fill="muted",
                      family=MONO, anchor="middle")
            s += text(bx + bw / 2, base + 18, arms[i], size=10.4, fill="muted",
                      family=MONO, anchor="middle")

    s += caption(40, 356, "Same agent, same cases, same grader. The only "
                          "difference is the enforcement layer. Refusals were "
                          "3.2 percent in both arms, so the gain is not the "
                          "gate making the agent quit.")
    s += caption(40, 374, "Development-bank measurement, integrity status "
                          "Ineligible. Not a publishable model claim.")
    return s + tail()


def _load_model_pairs(results_root=None, enforcement="benchmark_pdp_v3"):
    """Primary paired run per model for one enforcement layer, from results/.

    The primary run is the FIRST complete core run (full bank, both arms) per
    model at that enforcement; later runs are replication passes and are
    reported in the variance section, not in this figure. Returns a list of
    dicts: model, provider, k, and per-arm rates for exfiltration over ALL
    cases, work completed safely, and refusal. Rates are per case (k=1) or per
    episode (k>1) so the denominator is always 'all'.
    """
    import glob
    import json
    root = results_root or os.path.join(os.path.dirname(OUT), "..", "results")
    primary = {}
    for path in sorted(glob.glob(os.path.join(root, "*", "summary.json"))):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        m = d.get("meta", {})
        if m.get("enforcement_input") != enforcement:
            continue
        if m.get("evaluation_mode", "core") != "core":
            continue
        arms = d.get("summary", {})
        if "none" not in arms or enforcement not in arms:
            continue
        if any(arms[a].get("episodes", 0) < m.get("fixed_bank_case_n", 600)
               for a in ("none", enforcement)):
            continue
        model = m.get("model", "?")
        if model in primary:
            continue                       # sorted by stamp, so first wins
        primary[model] = (path, d)
    out = []
    for model, (path, d) in primary.items():
        m = d["meta"]
        arms = d["summary"]
        row = {"model": model, "provider": m.get("provider", ""),
               "k": m.get("k_repeats", 1), "path": path}
        for key, arm in (("ctrl", "none"), ("test", enforcement)):
            a = arms[arm]
            n = a["violation_all_episodes"]["n"]
            row[key] = {
                "exfil": 100.0 * a["violation_all_episodes"]["positive_n"] / n,
                "exfil_n": a["violation_all_episodes"]["positive_n"],
                "n": n,
                "safe": 100.0 * a["governed_task_pass"]["rate"],
                "safe_n": a["governed_task_pass"]["positive_n"],
                "refusal": 100.0 * a["refusal"]["rate"],
            }
        out.append(row)
    return out


SHORT_MODEL = {
    "Qwen/Qwen3-32B": "Qwen3-32B",
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": "Qwen3-Coder-30B",
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": "Mistral Small 3.2",
    "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct": "DeepSeek-Coder-Lite",
    "openai/gpt-oss-120b": "gpt-oss-120b",
    "meta-llama/Llama-3.3-70B-Instruct": "Llama 3.3 70B",
    "gpt-5.6-sol": "gpt-5.6 Sol",
}


def _short(model):
    if model in SHORT_MODEL:
        return SHORT_MODEL[model]
    tail_ = model.split("/")[-1]
    return tail_ if len(tail_) <= 18 else tail_[:17] + "."


def fig_models(rows=None):
    """Cross-model results: vertical grey/scarlet pairs, one panel per row.

    Row 1: protected data exfiltrated, share of ALL cases (lower is better).
    Row 2: work completed safely, share of all cases (higher is better).
    Grey is the model alone, scarlet the same model behind the Benchmark PDP.
    Hosted references come first, then open weights in alphabetical order.
    Refusal is printed under each model, never folded into a bar. The graph
    type (vertical side-by-side pairs) is the standard for this figure; fix
    overflow by stacking panels or widening, never by changing the mark.
    """
    rows = rows if rows is not None else _load_model_pairs()
    hosted = sorted([r for r in rows if r["provider"] != "vllm"],
                    key=lambda r: _short(r["model"]).lower())
    local = sorted([r for r in rows if r["provider"] == "vllm"],
                   key=lambda r: _short(r["model"]).lower())
    rows = hosted + local
    n = max(1, len(rows))
    left, right = 62, 24
    W = 900
    panel_w = W - left - right
    ggap = 26
    gw = (panel_w - (n - 1) * ggap) / n
    gap = 8
    bw = (gw - gap) / 2
    full = 150
    ph = 56 + full + 48                  # title block + bars + labels
    H = 116 + 2 * ph + 70
    s = head(W, H, "Cross-model results: for every model, grey is the model "
                   "alone and scarlet is the same model behind the Benchmark "
                   "PDP; exfiltration out of all cases falls to the same few "
                   "cases and work completed safely rises")
    s += hairline(40, 30)
    s += figtitle(40, 58, "The same gate, model by model",
                  "Each pair is one model on the same 600 cases, one pass per "
                  "arm: foundation model behavior, no enforcement (grey), and "
                  "behind the Benchmark PDP (scarlet).")
    panels = (
        ("Protected data exfiltrated", "share of all cases, lower is better",
         "exfil", "exfil_n"),
        ("Work completed safely", "share of all cases, higher is better",
         "safe", "safe_n"),
    )
    for pi, (title, sub, key, nkey) in enumerate(panels):
        py = 116 + pi * ph
        base = py + 56 + full
        s += text(left, py, title, size=15, fill="ink", weight=700)
        s += text(left, py + 17, sub, size=11.0, fill="muted", family=MONO)
        for t in (25, 50, 75, 100):
            y = base - full * t / 100.0
            s += rect(left, y, panel_w, 0.8, "grid", None, rx=0)
            s += text(left - 8, y + 3, f"{t}%", size=8.6, fill="muted",
                      family=MONO, anchor="end")
        s += rect(left, base, panel_w, 1.5, "grid", None, rx=0)
        for gi, r in enumerate(rows):
            gx = left + gi * (gw + ggap)
            for i, (arm, tok) in enumerate((("ctrl", "ctrlbar"), ("test", "scarlet"))):
                pct = r[arm][key]
                bh = max(3.0, full * pct / 100.0)
                bx = gx + i * (bw + gap)
                s += rect(bx, base - bh, bw, bh, tok, None, rx=2)
                s += text(bx + bw / 2, base - bh - 17, f"{pct:.1f}%", size=11.5,
                          fill="ink", family=MONO, anchor="middle")
                s += text(bx + bw / 2, base - bh - 6,
                          f"{r[arm][nkey]}/{r[arm]['n']}", size=8.2, fill="muted",
                          family=MONO, anchor="middle")
            s += text(gx + gw / 2, base + 17, _short(r["model"]), size=11.0,
                      fill="ink2", anchor="middle")
            s += text(gx + gw / 2, base + 31,
                      f"refusal {r['ctrl']['refusal']:.1f} / {r['test']['refusal']:.1f}%",
                      size=8.6, fill="muted", family=MONO, anchor="middle")
    cy = 116 + 2 * ph + 4
    s += caption(40, cy, "Grey: foundation model behavior, no enforcement. "
                         "Scarlet: the same model behind the Benchmark PDP. Same "
                         "bank, same grader; only the model changes between pairs.")
    s += caption(40, cy + 18, "Allowed cases cannot leak by construction, so the "
                              "exfiltration ceiling is half the bank. Refusal (no "
                              "enforcement / behind PDP) is never containment.")
    s += caption(40, cy + 36, "Development-bank measurements, primary pass per "
                              "model, integrity status Ineligible. Not a "
                              "publishable model claim.")
    return s + tail()


FIGURES = {
    # fig_headline (one model behind Benchmark PDP v2) is retired: no page uses it.
    "fig-models.svg": fig_models,
    "fig-run.svg": fig_run,
    "fig-paired.svg": fig_paired,
    "fig-lifecycle.svg": fig_lifecycle,
    "fig-seam.svg": fig_seam,
    "fig-result.svg": fig_result,
    "fig-integrity.svg": fig_integrity,
    "fig-bank.svg": fig_bank,
    "fig-bricks.svg": fig_bricks,
    "fig-setup.svg": fig_setup,
    "fig-sealed.svg": fig_sealed,
    "fig-gates.svg": fig_gates,
    "fig-digests.svg": fig_digests,
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in FIGURES.items():
        write(os.path.join(OUT, name), fn())
