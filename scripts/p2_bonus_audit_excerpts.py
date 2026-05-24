"""One-shot helper: generate opening/middle/closing excerpts for the 3
bonus the reference articles (id 14, 37, 38) into p2_artifacts/reference_excerpts/.

Mirrors p2_reference_excerpts.py but for the bonus-audit set rather than the
gate-verify set. Uses the same take_units / _middle_excerpt helpers so the
ZH char-aware slicing is consistent with the prior close-read."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from p2_reference_excerpts import (  # noqa: E402
    EXCERPT_UNITS,
    REFERENCE_DIR,
    build_excerpt,
    extract_reference_article,
    render_md,
)

OUT_DIR = _REPO_ROOT / "p2_artifacts" / "reference_excerpts"
BONUS_IDS = (14, 37, 38)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_id: dict[int, tuple[Path, str]] = {}
    for path in REFERENCE_DIR.glob("*.txt"):
        if path.name.endswith(".Identifier"):
            continue
        tid, body = extract_reference_article(path)
        if tid in BONUS_IDS:
            by_id[tid] = (path, body)

    for tid in BONUS_IDS:
        if tid not in by_id:
            print(f"missing id={tid}")
            continue
        _, body = by_id[tid]
        ex = build_excerpt(body)
        out = OUT_DIR / f"id_{tid}_reference.md"
        out.write_text(render_md(tid, "the #1 reference bonus", ex), encoding="utf-8")
        print(f"wrote {out.name}  total_units={ex['total_units']}  excerpt_units={EXCERPT_UNITS}")


if __name__ == "__main__":
    main()
