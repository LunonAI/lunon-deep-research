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

# Greptile PR #39 round-2: prior pattern `[^.]*\.` stopped at the FIRST dot,
# which inside "Building on §1.2 established in §3, this section…" matched the
# embedded decimal dot in "§1.2" and left ".2 established in §3, this section…"
# stranded as an orphan fragment. The corrected pattern uses non-greedy
# `[^\n]*?` plus a sentence-end lookahead `\.(?=\s|$)` — a period followed by
# whitespace or end-of-string, which is what a sentence-terminating period
# actually looks like. Dotted sub-section numbers (e.g. §1.2, §3.4.5) have a
# digit immediately after the dot, so the lookahead skips them.
_OPENING_TEMPLATE_PATTERN = re.compile(r"(?m)(^#{2}\s+[^\n]+\n+)(\s*Building on\b[^\n]*?\.(?=\s|$))[ \t]*")


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
    #
    # Greptile PR #39 round-2: the split MUST capture the inter-sentence
    # whitespace so we can rejoin with the verbatim separator. The prior
    # `re.split(r"(?<=[.!?])\s+", text)` consumed `\n\n` as part of the
    # match and the `" ".join(...)` collapse pushed the following `##`
    # heading inline with the preceding sentence — silently breaking
    # markdown rendering for every paragraph that happened to end in
    # `.\n\n## `. The capture group `(...)` makes `re.split` emit
    # separators as interleaved entries: [sent, sep, sent, sep, ..., sent].
    tokens = re.split(r"((?<=[.!?])\s+)", text)
    out_tokens: list[str] = []
    # `tokens` alternates: even indices are sentences, odd indices are
    # the inter-sentence whitespace (which may include `\n\n`).
    for i in range(0, len(tokens), 2):
        sentence = tokens[i]
        # Separator that FOLLOWED this sentence in the input (empty for
        # the final sentence). We carry the separator through verbatim.
        sep = tokens[i + 1] if i + 1 < len(tokens) else ""

        # Find all dangling refs in this sentence
        dangling_in_sentence = []
        for m in ref_pattern.finditer(sentence):
            num = m.group(1) or m.group(2) or m.group(3)
            if num and _looks_dangling(num):
                dangling_in_sentence.append((m.start(), m.end(), num))
        if not dangling_in_sentence:
            out_tokens.append(sentence)
            out_tokens.append(sep)
            continue
        # Compute remaining content after stripping the dangling refs.
        # If <15 chars or only punctuation remains, drop the sentence.
        stripped = sentence
        for start, end, _ in reversed(dangling_in_sentence):
            stripped = stripped[:start] + stripped[end:]
        residual = re.sub(r"[\s\.,;:!?\(\)\[\]]+", "", stripped)
        if len(residual) < 15:
            # Sentence has no meaningful content after removing the
            # dangling ref — delete it entirely (and its separator, so
            # we don't leave a dangling `\n\n` or `  ` in the output).
            # 15 chars is the heuristic bar; tighter and we'd preserve
            # dangler-only sentences, looser and we'd over-delete
            # legitimate prose.
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

        out_tokens.append(ref_pattern.sub(_rewrite, sentence))
        out_tokens.append(sep)
    text = "".join(out_tokens)

    return text, stats
