# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Self-contained HTML report for one AccessBench result bundle.

Pure standard library, no network, no external assets. Reads only what
`aggregate.py` already wrote to summary.json and what the runner wrote to the
run manifest; it never recomputes a number. Also holds the plain-English arm
labels that the CLI and the verifier share, so every human-readable surface
names the arms the same way.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BENCHMARK_PDP_ID = "benchmark_pdp_v3"
ENFORCEMENT_ALIASES = {"benchmark": BENCHMARK_PDP_ID}
BENCHMARK_PDP_FIRST_MENTION = "Benchmark PDP, the reference decision point"
CONTROL_ARM_LABEL = "foundation model behavior, no enforcement"
SMOKE_WARNING = "SMOKE SAMPLE, NOT A REPORTABLE RESULT"
FULL_LINE = "Full 600-case protocol, one pass per arm"
NOT_PUBLISHABLE_LINE = "Development-bank measurement; not a publishable model claim"

_FONT_TEXT = "Charter, 'Charter BT', 'Bitstream Charter', 'Charis SIL', ui-serif, Georgia, serif"
_FONT_MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
_CONTROL_GREY = "#8a8a93"
_SCARLET = "#c9364f"


def resolve_enforcement(value: str) -> tuple[str, str | None]:
    """Map a public alias to the built-in id; anything else passes through."""
    if value in ENFORCEMENT_ALIASES:
        return ENFORCEMENT_ALIASES[value], value
    return value, None


def enforced_arm_label(enforcement: str | None, *, first_mention: bool = False) -> str:
    """'behind the Benchmark PDP' for the built-in gate, else 'behind <id or host>'."""
    if enforcement in (BENCHMARK_PDP_ID, "benchmark"):
        name = BENCHMARK_PDP_FIRST_MENTION if first_mention else "Benchmark PDP"
        return f"behind the {name}"
    if enforcement and "://" in enforcement:
        return f"behind {urlparse(enforcement).hostname or enforcement}"
    return f"behind {enforcement or 'unknown enforcement'}"


def pct(block: dict | None) -> str:
    """Percent first, counts as subtext: 'NN.N% (k/n)'."""
    if not block or not block.get("n"):
        return "n/a"
    k = int(block.get("positive_n", 0))
    n = int(block["n"])
    return f"{100.0 * k / n:.1f}% ({k}/{n})"


def _arms(summary: dict) -> tuple[str, str | None]:
    arms = list(summary.get("summary", {}).keys())
    enforced = [a for a in arms if a != "none"]
    return "none", (enforced[0] if enforced else None)


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _row(label: str, value: Any, mono: bool = True) -> str:
    cls = ' class="mono"' if mono else ""
    return f"<tr><th>{_esc(label)}</th><td{cls}>{_esc(value)}</td></tr>"


def _bar_chart(control: dict, enforced: dict | None, enforced_label: str) -> str:
    """Vertical paired bars: grey (no enforcement) then scarlet (enforced), per metric."""
    pairs = [
        ("Protected data exfiltrated, share of all cases", "violation_all_episodes"),
        ("Work completed safely, share of all cases", "governed_task_pass"),
    ]
    width, height, base, top = 720, 320, 250, 40
    group_w = width // len(pairs)
    bar_w = 90
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        'aria-label="Paired vertical bars, no enforcement in grey, enforced arm in scarlet">'
    ]
    for g in (0, 25, 50, 75, 100):
        y = base - (base - top) * g / 100.0
        parts.append(
            f'<line x1="40" x2="{width - 20}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
            f'<text x="34" y="{y + 4:.1f}" class="tick" text-anchor="end">{g}%</text>'
        )
    for i, (title, key) in enumerate(pairs):
        x0 = i * group_w + group_w // 2
        for j, (block, color) in enumerate(((control.get(key), _CONTROL_GREY), ((enforced or {}).get(key), _SCARLET))):
            if not block or not block.get("n"):
                continue
            k, n = int(block.get("positive_n", 0)), int(block["n"])
            rate = k / n
            h = (base - top) * rate
            x = x0 - bar_w - 8 + j * (bar_w + 16)
            y = base - h
            parts.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{color}"/>')
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 18:.1f}" class="value" text-anchor="middle">'
                f'{100 * rate:.1f}%</text>'
            )
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 5:.1f}" class="count" text-anchor="middle">'
                f'{k}/{n}</text>'
            )
        parts.append(
            f'<text x="{x0}" y="{base + 22}" class="label" text-anchor="middle">{_esc(title)}</text>'
        )
    parts.append(f'<line x1="40" x2="{width - 20}" y1="{base}" y2="{base}" class="axis"/>')
    parts.append(
        f'<rect x="40" y="{height - 22}" width="14" height="14" fill="{_CONTROL_GREY}"/>'
        f'<text x="60" y="{height - 10}" class="label">{_esc(CONTROL_ARM_LABEL)}</text>'
        f'<rect x="380" y="{height - 22}" width="14" height="14" fill="{_SCARLET}"/>'
        f'<text x="400" y="{height - 10}" class="label">{_esc(enforced_label)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_report(
    summary: dict,
    manifest: dict | None,
    *,
    bundle_path: str,
    digests: dict[str, str],
    version: str,
) -> str:
    """Return the complete HTML document as a string."""
    meta = summary.get("meta", {})
    control_id, enforced_id = _arms(summary)
    blocks = summary.get("summary", {})
    control = blocks.get(control_id, {})
    enforced = blocks.get(enforced_id, {}) if enforced_id else None
    enforcement_input = meta.get("enforcement_input") or enforced_id
    enforced_label = enforced_arm_label(enforcement_input, first_mention=True)
    enforced_label_short = enforced_arm_label(enforcement_input)
    model = meta.get("model") or "unknown model"
    mode = meta.get("evaluation_mode")
    episodes = meta.get("episodes_run") or 0
    case_n = meta.get("fixed_bank_case_n") or (episodes // 2 if episodes else 0)
    smoke = mode != "core"
    banner_text = f"{SMOKE_WARNING} ({case_n} cases)" if smoke else FULL_LINE
    publication_eligible = meta.get("publication_eligible")
    integrity_status = (meta.get("integrity") or {}).get("integrity_status")
    config = (manifest or {}).get("config", {})
    git = (manifest or {}).get("git", {})

    def metrics_rows(block: dict | None) -> str:
        block = block or {}
        cells = [
            pct(block.get("governed_task_pass")),
            pct(block.get("violation_all_episodes")),
            pct(block.get("refusal")),
            pct(block.get("task_success")),
        ]
        return "".join(f'<td class="mono">{_esc(c)}</td>' for c in cells)

    decoding = config.get("decoding")
    observed_decoding = (manifest or {}).get("observed_decoding_requests") or []
    observed_models = (manifest or {}).get("observed_response_models") or []
    config_rows = [
        _row("Model", config.get("model") or model),
        _row("Provider-returned model id", ", ".join(observed_models) if observed_models else "not recorded"),
        _row("Enforcement id", enforcement_input),
        _row("Panel id", config.get("panel_id") or meta.get("panel_id")),
        _row("Catalog sha256", config.get("catalog_sha256") or meta.get("catalog_sha256")),
        _row("Harness commit", git.get("commit") or "not recorded"),
        _row("Harness dirty flag", git.get("dirty")),
        _row("Decoding (protocol)", json.dumps(decoding, sort_keys=True) if decoding else "not recorded"),
        _row("Decoding (as sent)", "; ".join(str(x) for x in observed_decoding) if observed_decoding else "not recorded"),
        _row("Started", (manifest or {}).get("started_at") or "not recorded"),
        _row("Finished", (manifest or {}).get("finished_at") or "not recorded"),
    ]
    digest_rows = [_row(name, value) for name, value in digests.items()]
    verify_cmd = f"accessbench verify {bundle_path}"
    eligibility_line = (
        f"publication_eligible: {json.dumps(publication_eligible)}; "
        f"integrity status: {integrity_status or 'not recorded'}"
    )
    css = f"""
:root {{ --bg:#f7f5f3; --ink:#1b1719; --muted:#7a7376; --grid:#e3dcda; --scarlet:{_SCARLET}; --grey:{_CONTROL_GREY}; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121114; --ink:#f4f2f0; --muted:#8f898c; --grid:#2b292c; }} }}
body {{ margin:0; padding:2rem 1.5rem; background:var(--bg); color:var(--ink); font-family:{_FONT_TEXT}; line-height:1.45; }}
main {{ max-width:60rem; margin:0 auto; }}
h1, h2 {{ font-weight:600; letter-spacing:-0.01em; }}
h1 {{ font-size:1.7rem; margin:1rem 0 0.25rem; }}
h2 {{ font-size:1.15rem; margin:2rem 0 0.5rem; border-bottom:1px solid var(--grid); padding-bottom:0.25rem; }}
.banner {{ border:2px solid var(--grey); padding:0.6rem 0.9rem; font-weight:600; }}
.banner.smoke {{ border-color:var(--scarlet); color:var(--scarlet); }}
.muted {{ color:var(--muted); }}
.mono, code, pre {{ font-family:{_FONT_MONO}; font-size:0.92em; }}
table {{ border-collapse:collapse; width:100%; margin:0.5rem 0; }}
th, td {{ text-align:left; padding:0.35rem 0.5rem; border-bottom:1px solid var(--grid); vertical-align:top; word-break:break-all; }}
th {{ font-weight:600; white-space:nowrap; }}
pre {{ background:transparent; border:1px solid var(--grid); padding:0.6rem; overflow-x:auto; }}
svg .grid {{ stroke:var(--grid); stroke-width:1; }}
svg .axis {{ stroke:var(--muted); stroke-width:1; }}
svg .tick, svg .count {{ fill:var(--muted); font-family:{_FONT_MONO}; font-size:11px; }}
svg .value {{ fill:var(--ink); font-family:{_FONT_MONO}; font-size:14px; font-weight:600; }}
svg .label {{ fill:var(--ink); font-family:{_FONT_TEXT}; font-size:13px; }}
footer {{ margin-top:2.5rem; color:var(--muted); font-size:0.9rem; }}
"""
    chart = _bar_chart(control, enforced, enforced_label_short)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AccessBench result: {_esc(model)} {_esc(enforced_label)}</title>
<style>{css}</style></head><body><main>
<div class="banner{' smoke' if smoke else ''}">{_esc(banner_text)}</div>
<h1>AccessBench result: {_esc(model)} {_esc(enforced_label)}</h1>
<p class="mono">{_esc(eligibility_line)}</p>
{'<p class="muted">' + _esc(NOT_PUBLISHABLE_LINE) + '</p>' if not publication_eligible else ''}
<h2>Two arms, side by side</h2>
<p class="muted">Grey: {_esc(CONTROL_ARM_LABEL)}. Scarlet: {_esc(enforced_label_short)}. Percent of all cases; counts under each bar.</p>
{chart}
<h2>Numbers of record</h2>
<div style="overflow-x:auto"><table><thead><tr><th>Arm</th><th>Work completed safely</th><th>Exfiltrated, share of all cases</th><th>Refusal</th><th>Task completed</th></tr></thead>
<tbody>
<tr><th>{_esc(CONTROL_ARM_LABEL)}</th>{metrics_rows(control)}</tr>
<tr><th>{_esc(enforced_label_short)}</th>{metrics_rows(enforced)}</tr>
</tbody></table></div>
<h2>Configuration</h2>
<table><tbody>{''.join(config_rows)}</tbody></table>
<h2>Verify this result</h2>
<pre>{_esc(verify_cmd)}</pre>
<table><tbody>{''.join(digest_rows)}</tbody></table>
<footer>AccessBench {_esc(version)}</footer>
</main></body></html>
"""
    return doc


def read_version(repo_root: Path) -> str:
    try:
        return (repo_root / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"
