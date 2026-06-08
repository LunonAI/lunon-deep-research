#!/usr/bin/env python3
"""Render the Lunon DeepResearch-Bench leaderboard hero chart (light + dark PNGs).

A clean ranked horizontal bar of RACE Overall (x100), Lunon highlighted at #1
against a muted field. FT/McKinsey styling: one accent + grey field, direct
value labels, no axes/gridlines/legend.

Source of truth: assets/data/leaderboard_gpt55.json
Output:          assets/leaderboard-overall-{light,dark}.png  (2x retina)

Usage:
    pip install -r requirements-viz.txt
    # one-time if no system Chrome:  python -c "import kaleido; kaleido.get_chrome_sync()"
    python scripts/render_leaderboard_chart.py

Note: kaleido renders via headless Chrome and uses system fonts. Generated once
on macOS and the PNGs are committed, so the shipped artifact is stable; a Linux
regen would fall back through the font stack to Arial.
"""

import json
import sys
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "assets" / "data" / "leaderboard_gpt55.json"

# Lunon brand palette (matches the README shields.io badges).
NAVY = "#0A2236"
BLUE = "#2563EB"
WHITE = "#FFFFFF"
FONT = "Helvetica Neue, Arial, sans-serif"  # HelveticaNeue on the Mac build; Arial elsewhere

THEMES = {
    "light": dict(
        bg=WHITE,
        text=NAVY,
        muted="#D5DAE0",
        sub="#5B6B7B",
        out=ROOT / "assets" / "leaderboard-overall-light.png",
    ),
    "dark": dict(
        bg=NAVY,
        text=WHITE,
        muted="#33495E",
        sub="#9AB0C4",
        out=ROOT / "assets" / "leaderboard-overall-dark.png",
    ),
}


def load():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    rows = sorted(doc["rows"], key=lambda r: r["overall"])  # ascending => #1 lands on top
    return rows, doc["_meta"]


def build(rows, theme):
    t = THEMES[theme]
    names = [r["model"] for r in rows]
    scores = [r["overall"] for r in rows]
    colors = [BLUE if r.get("lunon") else t["muted"] for r in rows]

    # Direct value labels: Lunon bold + blue "#1" chip; field muted.
    labels = []
    for r, s in zip(rows, scores, strict=True):
        if r.get("lunon"):
            labels.append(f"<b>{s:.1f}</b>")
        else:
            labels.append(f"<span style='color:{t['sub']}'>{s:.1f}</span>")

    # y-axis category labels: bold the Lunon row.
    ticks = [f"<b>{n}</b>" if r.get("lunon") else n for r, n in zip(rows, names, strict=True)]

    fig = go.Figure(
        go.Bar(
            x=scores,
            y=names,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0), cornerradius=3),
            text=labels,
            textposition="outside",
            cliponaxis=False,
            textfont=dict(family=FONT, size=15, color=t["text"]),
            width=0.66,
        )
    )
    fig.update_layout(
        title=dict(
            text=(
                "<b>DeepResearch-Bench — Overall</b>"
                f"<br><span style='font-size:13px;color:{t['sub']}'>"
                "RACE score (×100) · GPT-5.5 judge</span>"
            ),
            font=dict(family=FONT, size=22, color=t["text"]),
            x=0.0,
            xanchor="left",
            xref="paper",
            y=0.94,
            yref="container",
        ),
        paper_bgcolor=t["bg"],
        plot_bgcolor=t["bg"],
        font=dict(family=FONT, color=t["text"]),
        margin=dict(l=235, r=80, t=96, b=62),
        bargap=0.34,
        showlegend=False,
        width=900,
        height=480,
        annotations=[
            dict(
                text=(
                    "Source: muset-ai/DeepResearch-Bench (GPT-5.5 board) · "
                    "Lunon: validated harness, submission in processing · scores ×100"
                ),
                xref="paper",
                yref="paper",
                x=0.0,
                y=-0.14,
                xanchor="left",
                showarrow=False,
                font=dict(family=FONT, size=10.5, color=t["sub"]),
            )
        ],
    )
    fig.update_xaxes(visible=False, range=[0, max(scores) * 1.18], showgrid=False, zeroline=False)
    fig.update_yaxes(
        ticktext=ticks,
        tickvals=names,
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="",
        tickfont=dict(family=FONT, size=14, color=t["text"]),
    )
    return fig


def main():
    if not DATA.exists():
        sys.exit(f"missing data file: {DATA}")
    rows, _meta = load()
    for theme in ("light", "dark"):
        out = THEMES[theme]["out"]
        try:
            build(rows, theme).write_image(str(out), scale=2, width=900, height=480)
        except Exception as e:  # noqa: BLE001 - surface the kaleido/chrome hint
            sys.exit(
                f"export failed ({e!r}). If this is a Chrome-not-found error, run once:\n"
                '  python -c "import kaleido; kaleido.get_chrome_sync()"'
            )
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
