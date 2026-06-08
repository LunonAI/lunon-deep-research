#!/usr/bin/env python3
"""Render the "How it works" pipeline diagram (light + dark PNGs).

A restrained, premium diagram of the engine: a numbered vertical flow through
four stages (plan / research / write / edit), each a clean group of stage cards
tagged with the model that runs it, plus the research fan-out, the per-section
quality loop, and the deterministic post-pass chain. Neutral field + a single
blue accent on the flow spine, green only for the final node — Apple/McKinsey
restraint, not glow. Matches the leaderboard chart's toolchain (HTML/CSS ->
headless-Chromium screenshot, bundled Inter font, committed PNGs).

Source of truth: assets/data/architecture.json
Output:          assets/architecture-{light,dark}.png   (2x retina)

Usage:
    pip install -r requirements-viz.txt
    python -m playwright install chromium      # one-time
    python scripts/render_architecture_diagram.py
    python scripts/render_architecture_diagram.py --check   # models vs config.py

Faithful to deep_research/orchestrate.py (stage order + post-pass chain),
config.py (role -> model), state.py (PipelineState).
"""

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "assets" / "data" / "architecture.json"
FONTS = ROOT / "assets" / "fonts"

# Display name for each role's model (no provider noise — just the model).
MODELS = {"opus": "Opus", "gpt": "GPT-5.5", "nemo": "Nemotron", "deepseek": "DeepSeek", "det": "deterministic"}

THEMES = {
    "light": {
        "out": ROOT / "assets" / "architecture-light.png",
        "vars": {
            "--page-top": "#FFFFFF", "--page-bot": "#F6F8FB",
            "--text": "#0B2236", "--sub": "#54657A", "--faint": "#8593A4",
            "--card": "#FFFFFF", "--card-bd": "#E5E9EF",
            "--inset": "#F5F7FA", "--inset-bd": "#E8ECF2",
            "--spine": "#D4DCE6", "--accent": "#2563EB", "--accent-soft": "#2563EB", "--green": "#15A34A",
            "--sh1": "0 1px 2px rgba(10,34,54,.06),0 2px 6px rgba(10,34,54,.05)",
            "--mono": "#EEF2F7", "--mono-bd": "#E1E7EE", "--mono-tx": "#3C4B60",
        },
    },
    "dark": {
        "out": ROOT / "assets" / "architecture-dark.png",
        "vars": {
            "--page-top": "#0C2740", "--page-bot": "#08192B",
            "--text": "#ECF1F7", "--sub": "#9DB1C4", "--faint": "#6E8499",
            "--card": "rgba(255,255,255,.045)", "--card-bd": "rgba(255,255,255,.11)",
            "--inset": "rgba(255,255,255,.028)", "--inset-bd": "rgba(255,255,255,.08)",
            "--spine": "rgba(255,255,255,.17)", "--accent": "#3B82F6", "--accent-soft": "#74A8FF", "--green": "#27C16E",
            "--sh1": "0 1px 2px rgba(0,0,0,.35),0 2px 8px rgba(0,0,0,.22)",
            "--mono": "rgba(255,255,255,.04)", "--mono-bd": "rgba(255,255,255,.10)", "--mono-tx": "#C4D3E1",
        },
    },
}

W = 1140  # logical canvas width; PNG is 2x via device_scale_factor


def _loop_icon():
    return ('<svg class="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
            '<path d="M20 11.5a8 8 0 1 0-.7 4" stroke="var(--sub)" stroke-width="2" stroke-linecap="round"/>'
            '<path d="M20 4.5v5h-5" stroke="var(--sub)" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"/></svg>')


# --------------------------------------------------------------------------- #
def _font_faces():
    out = []
    for weight, fname in ((400, "Inter-Regular.woff2"), (600, "Inter-SemiBold.woff2"), (700, "Inter-Bold.woff2")):
        b64 = base64.b64encode((FONTS / fname).read_bytes()).decode()
        out.append(f"@font-face{{font-family:'Inter';font-style:normal;font-weight:{weight};font-display:block;"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    return "".join(out)


def _stage(st):
    cond = f'<span class="cond">{st["cond"].upper()}</span>' if st.get("cond") else ""
    return (f'<div class="stage"><div class="s-name">{st["name"]}{cond}</div>'
            f'<div class="s-model">{MODELS[st["model"]]}</div></div>')


def _fanout(f):
    cards = "".join(f'<span class="spec">{s}</span>' for s in f["specialists"])
    return (
        '<div class="inset">'
        f'<div class="inset-head"><b>5 specialists</b> dispatched in parallel'
        f'<span class="tagline">{f["model_full"]}</span></div>'
        f'<div class="spec-row">{cards}</div>'
        f'<div class="inset-note">{f["note"]}</div>'
        '</div>'
    )


def _loop(lp):
    steps = ' <span class="arr">&#8594;</span> '.join(lp["steps"])
    return (
        '<div class="inset loop">'
        f'{_loop_icon()}<div class="loop-tx"><b>per-section quality loop</b>&nbsp; '
        f'<span class="loop-steps">{steps}</span>'
        f'<span class="loop-tail">&nbsp;&nbsp;·&nbsp; {lp["note"]}</span></div>'
        '</div>'
    )


def _chain(ch):
    tags = "".join(f'<span class="mono">{p}</span>' for p in ch["passes"])
    return (
        '<div class="inset">'
        f'<div class="inset-head"><b>{ch["label"]}</b><span class="tagline">{ch["sub"]}</span></div>'
        f'<div class="chain-row">{tags}</div>'
        '</div>'
    )


def _row(node_cls, node_style, body, rail_cls=""):
    return (f'<div class="row"><div class="rail {rail_cls}">'
            f'<span class="node {node_cls}"{node_style}></span></div>'
            f'<div class="body">{body}</div></div>')


def _phase(ph):
    stages = "".join(_stage(s) for s in ph["stages"])
    extra = ""
    if "fanout" in ph:
        extra = _fanout(ph["fanout"])
    elif "loop" in ph:
        extra = _loop(ph["loop"])
    elif "chain" in ph:
        extra = _chain(ph["chain"])
    note = f'<div class="note">{ph["note"]}</div>' if ph.get("note") else ""
    body = (
        f'<div class="head"><span class="num">{ph["n"]}</span>'
        f'<span class="name">{ph["name"]}</span><span class="dot">·</span>'
        f'<span class="tag">{ph["tag"]}</span></div>'
        f'<div class="stages">{stages}</div>{extra}{note}'
    )
    return _row("ring", "", body)


STATIC_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:transparent}
#diagram{width:1140px;font-family:'Inter',-apple-system,Helvetica,Arial,sans-serif;color:var(--text);
  -webkit-font-smoothing:antialiased;padding:46px 50px 44px;border-radius:22px;
  background:linear-gradient(180deg,var(--page-top),var(--page-bot));
  border:1px solid var(--card-bd)}

.masthead{margin-bottom:26px}
.kicker{font-size:11.5px;font-weight:700;letter-spacing:.16em;color:var(--accent-soft);text-transform:uppercase}
.title{font-size:27px;font-weight:700;letter-spacing:-.4px;margin-top:9px;line-height:1.12}
.subtitle{font-size:15px;color:var(--sub);margin-top:8px;line-height:1.45}

/* vertical numbered flow */
.row{display:grid;grid-template-columns:46px 1fr;column-gap:20px}
.rail{position:relative}
.rail::before{content:"";position:absolute;left:22px;top:0;bottom:0;width:2px;background:var(--spine)}
.rail.start::before{top:11px}
.rail.finish::before{top:0;height:11px}
.node{position:absolute;left:22px;top:3px;width:16px;height:16px;border-radius:50%;
  transform:translateX(-50%);background:var(--page-top);box-sizing:border-box}
.node.ring{border:2px solid var(--accent)}
.node.entry{border:2px solid var(--spine)}
.node.done{background:var(--green);border:2px solid var(--green);box-shadow:0 0 0 4px color-mix(in srgb,var(--green) 15%,transparent)}

.body{padding-bottom:26px}
.io{font-size:13.5px;font-weight:600;color:var(--faint);letter-spacing:.01em;padding-top:1px}
.body.last{padding-bottom:0}
.fin{font-size:17px;font-weight:700;color:var(--text)}
.fin b{color:var(--green)}

.head{display:flex;align-items:baseline;flex-wrap:wrap;gap:0 10px}
.num{font-size:13px;font-weight:700;color:var(--accent-soft);letter-spacing:.06em}
.name{font-size:18.5px;font-weight:700;letter-spacing:-.2px}
.head .dot{color:var(--faint)}
.tag{font-size:14.5px;color:var(--sub)}

.stages{display:flex;flex-wrap:wrap;gap:9px;margin-top:13px}
.stage{display:flex;flex-direction:column;gap:2px;padding:9px 13px;border-radius:10px;
  background:var(--card);border:1px solid var(--card-bd);box-shadow:var(--sh1)}
.s-name{font-size:14.5px;font-weight:600;letter-spacing:-.1px;white-space:nowrap}
.s-model{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
.cond{font-size:9px;font-weight:700;letter-spacing:.05em;color:var(--accent-soft);
  border:1px solid var(--card-bd);border-radius:5px;padding:0 4px;margin-left:6px;vertical-align:middle}

/* inset sub-blocks (fan-out / loop / chain) */
.inset{margin-top:13px;padding:13px 15px;border-radius:12px;background:var(--inset);border:1px solid var(--inset-bd)}
.inset-head{font-size:13px;color:var(--sub);display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.inset-head b{color:var(--text);font-weight:700}
.tagline{font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);
  padding-left:9px;border-left:1px solid var(--card-bd)}
.inset-note{font-size:12.5px;color:var(--faint);margin-top:9px;line-height:1.45}
.spec-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:11px}
.spec{font-size:13px;font-weight:600;color:var(--text);background:var(--card);border:1px solid var(--card-bd);
  border-radius:8px;padding:6px 11px;box-shadow:var(--sh1)}

.inset.loop{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.ico{flex:0 0 auto}
.loop-tx{font-size:13.5px;color:var(--sub)}
.loop-tx b{color:var(--text);font-weight:700}
.loop-steps{font-weight:600;color:var(--text)}
.loop-tail{color:var(--faint)}
.arr{color:var(--faint);font-weight:400;padding:0 1px}

.chain-row{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
.mono{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:11.5px;color:var(--mono-tx);
  background:var(--mono);border:1px solid var(--mono-bd);border-radius:6px;padding:4px 8px}

.note{font-size:13px;color:var(--sub);margin-top:13px;line-height:1.45}
"""


def build_html(doc, theme):
    root = ":root{" + "".join(f"{k}:{v};" for k, v in THEMES[theme]["vars"].items()) + "}"
    rows = _row("entry", "", f'<div class="io">{doc["inflow"]}</div>', rail_cls="start")
    rows += "".join(_phase(p) for p in doc["phases"])
    rows += _row("done", "", f'<div class="fin"><b>↓</b>&nbsp; {doc["outflow"]}</div>',
                 rail_cls="finish") .replace('<div class="body">', '<div class="body last">')
    body = (
        '<div id="diagram">'
        f'<div class="masthead"><div class="kicker">{doc["kicker"]}</div>'
        f'<div class="title">{doc["title"]}</div>'
        f'<div class="subtitle">{doc["subtitle"]}</div></div>'
        f'<div class="flow">{rows}</div>'
        '</div>'
    )
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            + _font_faces() + root + STATIC_CSS
            + "</style></head><body>" + body + "</body></html>")


def render(doc):
    import io

    from PIL import Image
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for theme in ("light", "dark"):
                out = THEMES[theme]["out"]
                page = browser.new_page(viewport={"width": W, "height": 1600}, device_scale_factor=2)
                page.set_content(build_html(doc, theme), wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                shot = page.locator("#diagram").screenshot()
                page.close()
                im = Image.open(io.BytesIO(shot)).convert("RGB")
                im.quantize(colors=256, method=Image.Quantize.FASTOCTREE,
                            dither=Image.Dither.FLOYDSTEINBERG).save(out, optimize=True)
                print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")
        finally:
            browser.close()


def check(doc):
    """Drift guard. Each diagram model-key asserts a family/version about the live
    model id in config.py (the label "GPT-5.5" claims a gpt-5.5 id, "DeepSeek"
    claims a deepseek id, etc.). Verify those assertions against the *live* config
    for only the keys the diagram (`doc`) actually uses, so a model swap in
    config.py (e.g. zh_writer -> qwen) is flagged. Exits non-zero on mismatch."""
    sys.path.insert(0, str(ROOT))
    from deep_research import config

    roles = config.all_roles()
    # token the diagram's label for each key claims is present in the live model id
    asserts = {"opus": "opus", "gpt": "gpt-5.5", "nemo": "nemotron-3-super-120b", "deepseek": "deepseek"}
    live_id = {"opus": config.OPUS, "gpt": config.GPT55, "nemo": config.NEMOTRON,
               "deepseek": roles.get("zh_writer", "")}

    used = {s["model"] for ph in doc["phases"] for s in ph.get("stages", [])}
    used |= {ph[k]["model"] for ph in doc["phases"] for k in ("fanout", "loop") if k in ph}

    ok = True
    if unknown := used - set(MODELS):
        ok = False
        print(f"  unknown model keys in architecture.json: {sorted(unknown)}")
    for key in sorted(used & asserts.keys()):
        good = asserts[key] in live_id[key].lower()
        ok = ok and good
        print(f"  {key:9} label {MODELS[key]!r:11} expects {asserts[key]!r} in "
              f"{live_id[key]!r:42} [{'ok' if good else 'DRIFT'}]")
    # the fan-out spells out the full model name — it must still match the live Nemotron id
    for ph in doc["phases"]:
        if f := ph.get("fanout"):
            norm = lambda s: s.lower().replace("-", "").replace(" ", "").replace("/", "")  # noqa: E731
            good = norm(f["model_full"]) in norm(config.NEMOTRON)
            ok = ok and good
            print(f"  fan-out   {f['model_full']!r} vs {config.NEMOTRON!r} [{'ok' if good else 'DRIFT'}]")
    print("check:", "diagram labels match config" if ok else "DRIFT — update the diagram and re-render")
    return 0 if ok else 1


def main():
    if not DATA.exists():
        sys.exit(f"missing data file: {DATA}")
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    if "--check" in sys.argv:
        sys.exit(check(doc))
    try:
        render(doc)
    except Exception as e:  # noqa: BLE001 - surface the chromium hint
        sys.exit(f"render failed ({e!r}). If Chromium is missing, run once:\n"
                 "  python -m playwright install chromium")


if __name__ == "__main__":
    main()
