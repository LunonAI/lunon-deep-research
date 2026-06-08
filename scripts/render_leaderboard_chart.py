#!/usr/bin/env python3
"""Render the Lunon DeepResearch-Bench leaderboard hero chart (light + dark PNGs).

A premium "glass rail" ranked bar of RACE Overall (x100): a frosted-glass panel
on a brand-gradient backdrop, the field as quiet frosted slabs, and Lunon as the
only lit object (blue gradient bar + glow). Built as a self-contained HTML/CSS
document and screenshotted with headless Chromium (Playwright), which is the only
way to get real backdrop-filter glass, gradients, glow, and bundled web fonts.

Source of truth: assets/data/leaderboard_gpt55.json
Bundled assets (offline, deterministic): assets/fonts/Inter-*.woff2 (SIL OFL 1.1)
Output: assets/leaderboard-overall-{light,dark}.png  (2x retina)

Usage:
    pip install -r requirements-viz.txt
    playwright install chromium      # one-time: downloads the version-locked browser
    python scripts/render_leaderboard_chart.py

Note: fonts are base64-embedded @font-face (no network at render) and gated on
document.fonts.ready before capture, so the committed PNGs are reproducible.
"""

import base64
import html
import json
import sys
from pathlib import Path
from string import Template

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "assets" / "data" / "leaderboard_gpt55.json"
FONTS = ROOT / "assets" / "fonts"

DEVICE_SCALE = 2
VIEWPORT = {"width": 1000, "height": 820}

OUT = {
    "light": ROOT / "assets" / "leaderboard-overall-light.png",
    "dark": ROOT / "assets" / "leaderboard-overall-dark.png",
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def font_faces() -> str:
    faces = [
        (400, "Inter-Regular.woff2"),
        (600, "Inter-SemiBold.woff2"),
        (700, "Inter-Bold.woff2"),
    ]
    return "\n".join(
        f"@font-face{{font-family:'Inter';font-style:normal;font-weight:{w};"
        f"font-display:block;src:url(data:font/woff2;base64,{_b64(FONTS / f)}) format('woff2');}}"
        for w, f in faces
    )


def month_year(iso_date: str) -> str:
    """'2026-06-08' -> 'JUN 2026'."""
    y, m, _d = iso_date.split("-")
    return f"{_MONTHS[int(m) - 1]} {y}"


def load():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    rows = sorted(doc["rows"], key=lambda r: r["overall"], reverse=True)  # #1 first
    return rows, doc["_meta"]


def rows_html(rows) -> str:
    top = max(r["overall"] for r in rows)
    out = []
    for r in rows:
        lunon = bool(r.get("lunon"))
        pct = r["overall"] / top * 100.0
        row_cls = "row row--lunon" if lunon else "row"
        bar_cls = "bar bar--lunon" if lunon else "bar"
        out.append(
            f'<div class="{row_cls}">'
            f'<div class="name">{html.escape(r["model"])}</div>'
            f'<div class="track"><div class="{bar_cls}" style="width:{pct:.2f}%"></div></div>'
            f'<div class="score">{r["overall"]:.1f}</div>'
            f"</div>"
        )
    return "\n".join(out)


_HTML = Template(r"""<!doctype html><html><head><meta charset="utf-8"><style>
$font_faces
*{margin:0;padding:0;box-sizing:border-box}
html{font-family:'Inter',system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;font-feature-settings:'tnum' 1,'cv05' 1;font-variant-numeric:tabular-nums;}

/* ---- tokens: DARK (default) ---- */
body{
  --bg1:#123249; --bg2:#0A2236; --bg3:#071826; --bloom:rgba(37,99,235,.20);
  --text:#FFFFFF; --sub:#9AB0C4; --name:rgba(255,255,255,.82); --score:#9AB0C4;
  --panel-bg:rgba(13,33,52,.55); --panel-border:rgba(255,255,255,.10);
  --panel-shadow:inset 0 1px 0 rgba(255,255,255,.14),0 30px 60px -20px rgba(0,0,0,.55),0 2px 8px rgba(0,0,0,.30);
  --track-bg:rgba(255,255,255,.05); --track-shadow:inset 0 1px 2px rgba(0,0,0,.35);
  --field-bar:linear-gradient(180deg,rgba(176,196,216,.26),rgba(176,196,216,.15));
  --field-border:rgba(255,255,255,.08); --field-inner:inset 0 1px 0 rgba(255,255,255,.10);
  --lunon-glow:inset 0 1px 0 rgba(255,255,255,.45),0 0 0 1px rgba(37,99,235,.55),0 6px 24px -3px rgba(37,99,235,.60),0 2px 10px rgba(37,99,235,.40);
  --divider:rgba(255,255,255,.09); --meta-bg:rgba(255,255,255,.06); --meta-border:rgba(255,255,255,.12);
  --win-bg:rgba(37,99,235,.13); --win-border:rgba(37,99,235,.22);
}
/* ---- tokens: LIGHT overrides ---- */
body.theme-light{
  --bg1:#FFFFFF; --bg2:#F4F7FB; --bg3:#E7EEF6; --bloom:rgba(37,99,235,.07);
  --text:#0A2236; --sub:#5B6B7B; --name:rgba(10,34,54,.82); --score:#5B6B7B;
  --panel-bg:rgba(255,255,255,.62); --panel-border:rgba(10,34,54,.08);
  --panel-shadow:inset 0 1px 0 rgba(255,255,255,.85),0 24px 50px -22px rgba(10,34,54,.22),0 2px 6px rgba(10,34,54,.06);
  --track-bg:rgba(10,34,54,.045); --track-shadow:inset 0 1px 2px rgba(10,34,54,.10);
  --field-bar:linear-gradient(180deg,rgba(120,140,162,.24),rgba(120,140,162,.14));
  --field-border:rgba(10,34,54,.06); --field-inner:inset 0 1px 0 rgba(255,255,255,.65);
  --lunon-glow:inset 0 1px 0 rgba(255,255,255,.55),0 0 0 1px rgba(37,99,235,.30),0 8px 24px -6px rgba(37,99,235,.40);
  --divider:rgba(10,34,54,.08); --meta-bg:rgba(10,34,54,.04); --meta-border:rgba(10,34,54,.08);
  --win-bg:rgba(37,99,235,.06); --win-border:rgba(37,99,235,.16);
}

#page{ width:948px; padding:44px;
  background:
    radial-gradient(42% 55% at 12% 6%, var(--bloom), transparent 70%),
    radial-gradient(125% 125% at 18% 0%, var(--bg1) 0%, var(--bg2) 55%, var(--bg3) 100%);
}
.panel{ border-radius:28px; padding:34px 40px;
  background:var(--panel-bg);
  -webkit-backdrop-filter:blur(20px) saturate(135%); backdrop-filter:blur(20px) saturate(135%);
  border:1px solid var(--panel-border); box-shadow:var(--panel-shadow);
}
.head{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px;}
.title{ font-size:26px; font-weight:700; letter-spacing:-.01em; color:var(--text); line-height:1.15;}
.dek{ margin-top:7px; font-size:14px; font-weight:400; color:var(--sub);}
.meta{ flex:none; margin-top:3px; font-size:11px; font-weight:600; letter-spacing:.07em; text-transform:uppercase;
  color:var(--sub); background:var(--meta-bg); border:1px solid var(--meta-border); padding:7px 13px; border-radius:999px;}
.rule{ height:1px; background:var(--divider); margin:22px 0;}
.board{ display:flex; flex-direction:column; gap:14px;}
.row{ position:relative; display:grid; grid-template-columns:250px 1fr 64px; column-gap:30px; align-items:center; height:34px;}
.row--lunon::before{ content:""; position:absolute; inset:-7px -16px; border-radius:13px;
  background:var(--win-bg); box-shadow:inset 0 0 0 1px var(--win-border);}
.row--lunon>*{ position:relative; z-index:1;}
.name{ font-size:15px; font-weight:400; color:var(--name); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.track{ position:relative; height:18px; border-radius:8px; overflow:hidden; background:var(--track-bg); box-shadow:var(--track-shadow);}
.bar{ height:100%; border-radius:8px; background:var(--field-bar); border:1px solid var(--field-border); box-shadow:var(--field-inner);}
.score{ text-align:right; font-size:16px; font-weight:600; color:var(--score);}
.row--lunon .name{ font-weight:700; color:var(--text); letter-spacing:-.005em;}
.row--lunon .score{ font-size:19px; font-weight:700; color:var(--text);}
.bar--lunon{ border:1px solid transparent;
  background:linear-gradient(100deg,#1E5BE6 0%,#2563EB 42%,#3B82F6 100%); box-shadow:var(--lunon-glow);}
.src{ font-size:11px; font-weight:400; color:var(--sub);}
</style></head><body class="$theme_class">
<div id="page"><section class="panel">
  <header class="head">
    <div class="titles"><h1 class="title">$title</h1><p class="dek">$dek</p></div>
    <span class="meta">$meta</span>
  </header>
  <div class="rule"></div>
  <div class="board">
$rows
  </div>
  <div class="rule"></div>
  <footer class="src">$source</footer>
</section></div>
</body></html>""")


def build_html(rows, meta, theme: str) -> str:
    return _HTML.safe_substitute(
        font_faces=font_faces(),
        theme_class=f"theme-{theme}",
        title="DeepResearch-Bench — Overall",
        dek=f"RACE score (×100) · {html.escape(meta['judge'])} judge",
        meta=f"{len(rows)} AGENTS · {month_year(meta['generated'])}",
        rows=rows_html(rows),
        source=(
            "Source: muset-ai/DeepResearch-Bench (GPT-5.5 board) · "
            "Lunon: validated harness, submission in processing · scores ×100"
        ),
    )


def render(content: str, out: Path, scale: int) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--force-color-profile=srgb"])
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=scale)
        page = ctx.new_page()
        page.set_content(content, wait_until="load")
        page.evaluate("async () => { await document.fonts.ready; }")
        page.locator("#page").screenshot(path=str(out))
        browser.close()


def main() -> None:
    if not DATA.exists():
        sys.exit(f"missing data file: {DATA}")
    rows, meta = load()
    for theme in ("light", "dark"):
        out = OUT[theme]
        try:
            render(build_html(rows, meta, theme), out, DEVICE_SCALE)
        except Exception as e:  # noqa: BLE001 - surface the playwright-install hint
            sys.exit(
                f"render failed ({e!r}). If this is a browser-not-found error, run once:\n  playwright install chromium"
            )
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
