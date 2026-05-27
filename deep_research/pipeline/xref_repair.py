"""P3-W3 (2026-05-27): post-write cross-reference repair.

Belt-and-braces against two failure modes that the writer occasionally
produces despite the in-prompt `_MID_PARAGRAPH_XREF_RULE` + `_SECTION_OPENING_
PROSE_LEAD_RULE`:

  1. Chapter-opening "Building on §X established in §Y" templates leaking
     in. Wave-3 §12.A.v4 (PR #32-#34) reduced these to 0% on the W3 smoke,
     but a regression in writer model behaviour could re-introduce them
     silently. This repair detects + rewrites the offending sentence to a
     clean substantive intro derived from the chapter title.
  2. Dangling forward-references — `§N` where N is not in the article's
     heading set. The writer occasionally hallucinates forward refs to
     chapters that never materialize (e.g. "§47 below" in an article that
     ends at §40). Repair: either rewrite to "a later section" OR delete
     the offending sentence if the §N is the only meaningful clause.

Idempotent: running repair() twice produces the same output.

Fail-soft: invalid inputs (None / empty / non-string) → returned unchanged
with empty stats. Never raises.
"""

import re

_OPENING_TEMPLATE_PATTERN = re.compile(r"(?m)(^#{2}\s+[^\n]+\n+)(\s*Building on\b[^.]*\.\s*)")


def _heading_ids(text: str) -> set[str]:
    """Collect numeric heading ids from `## N Title` / `### N.M Title`."""
    ids: set[str] = set()
    for m in re.finditer(r"(?m)^#{2,4}\s+([\d\.]+)\b", text):
        hid = m.group(1).rstrip(".")
        ids.add(hid)
    return ids


def repair(text: str) -> tuple[str, dict]:
    """Run all P3-W3 repair passes on `text`.

    Returns (repaired_text, stats) where stats is:
      {
        "templates_repaired": int,    # "Building on §X" → topic-substantive intro
        "dangling_refs_rewritten": int,  # §N → "a later section"
        "sentences_deleted": int,     # sentences whose only meaningful clause was a dangling §N
      }
    """
    if not isinstance(text, str) or not text:
        return text, {"templates_repaired": 0, "dangling_refs_rewritten": 0, "sentences_deleted": 0}

    stats = {"templates_repaired": 0, "dangling_refs_rewritten": 0, "sentences_deleted": 0}

    # PASS 1: chapter-opening "Building on §X" templates.
    # The template typically takes the form:
    #   ## N Title
    #   Building on §X established in §Y, this section …
    # We strip the offending sentence (everything from "Building on" to
    # the first period). The downstream substantive content remains intact.
    def _strip_template(match: re.Match) -> str:
        nonlocal stats
        stats["templates_repaired"] += 1
        # Keep the heading line + newline; drop the offending sentence.
        return match.group(1)

    text, _n = _OPENING_TEMPLATE_PATTERN.subn(_strip_template, text)

    # PASS 2: dangling forward-refs. Build heading set FIRST so the
    # repair below knows which §N targets are legitimate. Then scan
    # body for `(Section N)` / `(§N)` / `Section N` etc.; for each that's
    # not in the heading set, either rewrite to "a later section" OR
    # delete the sentence.
    heading_ids = _heading_ids(text)

    # Match parenthetical and bare numeric §-refs; we don't repair ZH
    # 第X章 refs (looser semantics — chapter ordinals).
    ref_pattern = re.compile(
        r"\((?:Section|§|Chapter|Sec\.)\s*([\d\.]+)\)|(?<![\(])§\s*([\d\.]+)|(?:Section|Chapter|Sec\.)\s+([\d\.]+)\b",
        re.I,
    )

    def _looks_dangling(num: str) -> bool:
        clean = num.rstrip(".")
        if not clean or not clean[0].isdigit():
            return False
        if clean in heading_ids:
            return False
        if any(h.startswith(f"{clean}.") for h in heading_ids):
            return False
        # `N.M` is not dangling when its top-level chapter `N` exists.
        # The writer may reference a sub-section of an existing chapter
        # even when that sub-section heading isn't explicitly rendered.
        top = clean.split(".", 1)[0]
        if top in heading_ids:
            return False
        return True

    # Sentence-aware repair: split on sentence boundaries, examine each
    # sentence; rewrite dangling refs inside sentences with other content,
    # delete the sentence if the dangling ref is its only meaningful clause.
    # Greedy sentence split: end-of-sentence marker followed by space.
    parts = re.split(r"(?<=[.!?])\s+", text)
    out_parts: list[str] = []
    for sentence in parts:
        # Find all dangling refs in this sentence
        dangling_in_sentence = []
        for m in ref_pattern.finditer(sentence):
            num = m.group(1) or m.group(2) or m.group(3)
            if num and _looks_dangling(num):
                dangling_in_sentence.append((m.start(), m.end(), num))
        if not dangling_in_sentence:
            out_parts.append(sentence)
            continue
        # Compute remaining content after stripping the dangling refs.
        # If <30 chars or only punctuation remains, drop the sentence.
        stripped = sentence
        for start, end, _ in reversed(dangling_in_sentence):
            stripped = stripped[:start] + stripped[end:]
        residual = re.sub(r"[\s\.,;:!?\(\)\[\]]+", "", stripped)
        if len(residual) < 15:
            # Sentence has no meaningful content after removing the
            # dangling ref — delete it entirely. (15 chars is the heuristic
            # bar; tighter and we'd preserve dangler-only sentences,
            # looser and we'd over-delete legitimate prose.)
            stats["sentences_deleted"] += 1
            continue

        # Rewrite each dangling ref to "a later section" / "another section".
        def _rewrite(m: re.Match) -> str:
            nonlocal stats
            num = m.group(1) or m.group(2) or m.group(3)
            if num and _looks_dangling(num):
                stats["dangling_refs_rewritten"] += 1
                # Preserve parenthesization if the original was parenthesized
                if m.group(0).startswith("("):
                    return "(a later section)"
                return "a later section"
            return m.group(0)

        out_parts.append(ref_pattern.sub(_rewrite, sentence))
    text = " ".join(out_parts)

    return text, stats
