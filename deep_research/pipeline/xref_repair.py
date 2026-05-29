"""P3-W3 (2026-05-27): post-write cross-reference repair.

Belt-and-braces against two failure modes that the writer occasionally
produces despite the in-prompt `_MID_PARAGRAPH_XREF_RULE` + `_SECTION_OPENING_
PROSE_LEAD_RULE`:

  1. Chapter-opening "Building on §X established in §Y" templates leaking
     in. Wave-3 §12.A.v4 (PR #32-#34) reduced these to 0% on the W3 smoke,
     but a regression in writer model behaviour could re-introduce them
     silently. This repair detects + rewrites the offending sentence to a
     clean substantive intro derived from the chapter title.
  2. Dangling forward-references — `§N` / `§N.M` where the target is not in
     the article's heading set. The writer occasionally hallucinates forward
     refs to chapters that never materialize (e.g. "§47 below" in an article
     that ends at §40, or "§5.16" when chapter 5 only renders §5.1–§5.4).
     Repair (G2, 2026-05-28): EXCISE the dangling ref and clean up the orphan
     glue it leaves (list commas, range dashes, empty parens) — NOT rewrite it
     to "a later section" (which manufactured grammar breaks like "the Next
     Dimension a later section cited on…" and range-collapse artifacts like
     "§2–a later section"). If the ref is the sentence's only meaningful
     clause, delete the sentence.

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
#
# Greptile PR #39 round-3: `re.I` aligns this strip pattern with the
# auditor's `opening_template_pattern` in
# `writing_rules.check_xref_quality` (which is already case-insensitive).
# Without the flag, a model regression that emitted lowercase
# `"## 2 Foo\n\nbuilding on §1 …"` would slip past `repair()` unchanged
# while `check_xref_quality` reported `opening_template_violations=1` —
# a false divergence between what the post-write pass "repaired" and
# what the auditor sees. The `^##` anchor (no letters) already
# prevents false positives from mid-paragraph "building on" prose
# regardless of the flag.
_OPENING_TEMPLATE_PATTERN = re.compile(
    r"(?m)(^#{2}\s+[^\n]+\n+)(\s*Building on\b[^\n]*?\.(?=\s|$))[ \t]*",
    re.I,
)


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
        "dangling_refs_excised": int,  # §N / §N.M removed (orphan glue cleaned up)
        "sentences_deleted": int,     # sentences whose only meaningful clause was a dangling §N
      }
    """
    if not isinstance(text, str) or not text:
        return text, {"templates_repaired": 0, "dangling_refs_excised": 0, "sentences_deleted": 0}

    # G2 (Greptile PR #62): the `_SENT = "\x00"` excision marker assumes NUL
    # never occurs in article text. Enforce that invariant at the entry point —
    # if an upstream pass emits embedded NUL bytes, the `_cleanup_excised`
    # regexes would silently mis-process those positions as if they were
    # excision markers. Stripping NULs here keeps the sentinel unambiguous.
    text = text.replace("\x00", "")

    stats = {"templates_repaired": 0, "dangling_refs_excised": 0, "sentences_deleted": 0}

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
    # not in the heading set, either excise the ref (G2) OR delete the
    # sentence when the ref is its only meaningful clause.
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
        # `N.M` is valid only when a DEEPER heading `N.M(.x)` actually renders.
        if any(h.startswith(f"{clean}.") for h in heading_ids):
            return False
        # G12 (2026-05-28): the prior `top in heading_ids` exemption treated
        # any `N.M` as valid whenever its top chapter `N` existed — so `§5.16`
        # passed when chapter 5 rendered only §5.1–§5.4 (id=91 leaked §5.16/
        # §5.31/§5.42; id=14/§9.3; id=37/§3.4.2). A reference to a sub-section
        # that never materializes is a broken nav pointer. Strict rule (no
        # top-chapter exemption, no flat-chapter carve-out): if neither the
        # exact id nor a deeper id renders, it is dangling.
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
    # G2 (2026-05-28): EXCISE dangling refs rather than rewrite them to
    # "a later section". Each excised ref is first replaced by a private
    # marker (`_SENT`, a NUL char that never occurs in article text); a
    # second cleanup pass then absorbs the orphan GLUE the removed ref used
    # to anchor — but ONLY glue directly adjacent to a marker, so legitimate
    # em-dashes/commas elsewhere in the prose are untouched. This is what
    # makes range cases ("§9–§15" with §15 dangling → "§9", not "§9–") and
    # list cases ("across §5.16, §5.31, §5.42" → "across") clean instead of
    # leaving orphan dashes/commas. Closures defined ONCE before the loop so
    # the heading-guard path on the first iteration can call them.
    _SENT = "\x00"

    def _excise(m: re.Match) -> str:
        nonlocal stats
        num = m.group(1) or m.group(2) or m.group(3)
        if num and _looks_dangling(num):
            stats["dangling_refs_excised"] += 1
            return _SENT
        return m.group(0)

    def _cleanup_excised(s: str) -> str:
        if _SENT not in s:
            return s
        # Absorb glue immediately adjacent to a marker (range dash either
        # side, list comma either side, enclosing parens) BEFORE collapsing
        # the marker itself. Each rule is anchored on `_SENT`, so a dash or
        # comma that is NOT next to a removed ref is left alone.
        s = re.sub(rf"{_SENT}\s*[–—-]", _SENT, s)
        s = re.sub(rf"[–—-]\s*{_SENT}", _SENT, s)
        s = re.sub(rf"{_SENT}\s*,", _SENT, s)
        s = re.sub(rf",\s*{_SENT}", _SENT, s)
        # G2 (Greptile PR #62 issue 1): absorb an English conjunction stranded
        # next to a marker by the excision. After the comma rules above, an
        # all-dangling list like "§5.16, §5.31, and §5.42" collapses to
        # "\x00 \x00 and \x00", leaving "and" orphaned between markers — which
        # would surface as prose like "scattered across and throughout". These
        # rules absorb a conjunction ONLY when it is directly adjacent to a
        # marker (whitespace-separated), so mid-sentence conjunctions in normal
        # prose ("See \x00 today and tomorrow") are left untouched.
        s = re.sub(rf"\b(?:and|or)\s+{_SENT}", _SENT, s, flags=re.I)
        s = re.sub(rf"{_SENT}\s+(?:and|or)\b", _SENT, s, flags=re.I)
        s = re.sub(rf"\(\s*{_SENT}\s*\)", _SENT, s)
        # G2 (Greptile PR #62 issue 2): a marker at the very start/end of the
        # (sub)string has no neighbouring token to join, so collapse it to
        # nothing — otherwise the general interior rule below would leave a
        # spurious leading/trailing space (e.g. "§99 explains this" → leading
        # " explains this"). Run before the interior collapse.
        s = re.sub(rf"^\s*{_SENT}\s*", "", s)
        s = re.sub(rf"\s*{_SENT}\s*$", "", s)
        # Collapse every remaining (interior) marker (and surrounding
        # whitespace) to one space.
        s = re.sub(rf"\s*{_SENT}\s*", " ", s)
        # Normalise the seams left behind.
        s = re.sub(r"\(\s*\)", "", s)  # empty parens
        s = re.sub(r"\s+([,.;:!?])", r"\1", s)  # space before punctuation
        s = re.sub(r"\(\s+", "(", s)
        s = re.sub(r"\s+\)", ")", s)
        s = re.sub(r"[ \t]{2,}", " ", s)
        return s

    # Greptile PR #39 round-4: scope the sub to body lines only. `ref_pattern`'s
    # third alternation matches title words like "Chapter 47" / "Section 99" in
    # headings (`## 5 Chapter 47 Overview`). A naive whole-sentence sub would
    # excise those, corrupting the navigational layer. Title text is naming the
    # chapter, not navigating to it — leave it alone. The line-by-line filter
    # applies excision only to non-heading lines; heading-marker lines
    # (`^#{2,4}\s+`) pass through verbatim. The hot-path `re.search` avoids the
    # split/join overhead for the common case of a token with no heading.
    def _excise_body_only(text: str) -> str:
        if not re.search(r"(?m)^#{2,4}\s+", text):
            return _cleanup_excised(ref_pattern.sub(_excise, text))
        return "\n".join(
            line if re.match(r"^#{2,4}\s+", line) else _cleanup_excised(ref_pattern.sub(_excise, line))
            for line in text.split("\n")
        )

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
            # Greptile PR #39 round-3: heading-rooted token guard.
            # The sentence splitter `re.split(r"((?<=[.!?])\s+)", text)`
            # groups a chapter heading with the first body sentence
            # that follows it, because markdown headings don't end in
            # `.!?` — there's no split-point between `## N Title\n\n`
            # and the first body sentence. For short chapter names
            # ("Results", "Summary", "Overview", "Methods" — all ≤7
            # letters), the residual after stripping a dangling ref
            # includes the heading characters, e.g. `"## 1 Results\n\n
            # See (Section 99)."` → residual `"##1ResultsSee"` = 13
            # chars < 15 → token deleted, heading silently destroyed.
            # The excise path handles this safely (heading preserved,
            # dangler excised with glue cleanup), so we route
            # heading-rooted tokens there instead of deleting. We use
            # `(?m)^#{2,4}\s+` (multiline + 2-4 hashes) so any `##`/
            # `###`/`####` heading line inside the token survives.
            if re.search(r"(?m)^#{2,4}\s+", sentence):
                # Greptile PR #39 round-4: scope excision to body lines only.
                # See `_excise_body_only` docstring above the loop —
                # without this, heading titles containing "Chapter N" or
                # "Section N" would be excised by `ref_pattern`'s third
                # alternation, silently corrupting the navigational layer.
                out_tokens.append(_excise_body_only(sentence))
                out_tokens.append(sep)
                continue
            # Sentence has no meaningful content after removing the
            # dangling ref — delete it entirely. 15 chars is the
            # heuristic bar; tighter and we'd preserve dangler-only
            # sentences, looser and we'd over-delete legitimate prose.
            stats["sentences_deleted"] += 1
            # Greptile PR #39 round-2: do NOT drop the deleted sentence's
            # trailing `sep`. When the dangler-only sentence ends a
            # paragraph (its sep is `\n\n`), discarding it collapses the
            # following `## N` heading inline with the preceding sentence
            # — silently producing invalid markdown. Concrete failure:
            # `"## 1 Intro\n\nReal content. See (Section 99).\n\n## 2 Body"`
            # would become `"...Real content. ## 2 Body"` (heading inline).
            # Fix: carry the deleted sentence's sep forward onto the
            # preceding sep slot when it is more newline-rich, so the
            # next surviving sentence (or heading) retains its block-
            # level prefix. The excise path already preserves sep
            # unconditionally; this restores symmetry.
            if out_tokens and sep.count("\n") > out_tokens[-1].count("\n"):
                out_tokens[-1] = sep
            elif not out_tokens and sep:
                # Deletion at the very start of the text — no preceding
                # sep to merge into. Emit sep as a leading separator so
                # the first surviving sentence keeps its prefix.
                out_tokens.append(sep)
            continue

        # Excise each dangling ref (G2) and clean up the orphan glue.
        # `_excise`/`_excise_body_only` are hoisted above the loop so the
        # heading-guard path can share the same closures. `_excise_body_only`
        # scopes the sub to body lines so heading titles like "Chapter 47"
        # aren't corrupted — important here too because a long-bodied
        # sentence whose token includes a leading heading line still hits
        # this default branch (residual ≥ 15).
        out_tokens.append(_excise_body_only(sentence))
        out_tokens.append(sep)
    text = "".join(out_tokens)

    return text, stats
