"""P2-Wave-2-A: CAPEL countdown-marker post-strip.

CAPEL (arXiv 2508.13805) instructs the writer to emit inline countdown
markers `<N>word<N-1>word...<0>` so the model is forced to count down to
the target length. This module strips the markers from the writer's output
before downstream nodes (grounding, inner_loop, refiner, validation) ever
see the text.

Strip is fail-soft: if the writer never used markers, the regex finds
nothing and the original text is returned. Violation = back-to-back
markers like `<5><4>` with no intervening content token; we count these
so a high violation rate surfaces in drift telemetry without blocking
the pipeline.

P2 Wave 0 (§11, 2026-05-26): id=91 smoke surfaced word-fragmentation —
the writer interpreted "one content token per marker" at the BPE-subword
level, so multi-syllable words landed as `Sag itt arius` and dotted
heading numbers as `## 4 . 1 . 1`. After marker strip we now run two
conservative repair passes that only fire when markers were actually
present: a heading-line dot-number rejoin (high precision because
numbering shouldn't have spaces) and a word-fragment rejoin (lower
precision, guarded by stopword filter + length thresholds). The
authoritative defense is on the writer side via the strengthened
`writing_rules.capel_directive`; this is a safety net for cases where
the writer ignores the directive.
"""

from __future__ import annotations

import re

# CAPEL marker token: `<` then 1-5 digits then `>`. Tight digit range to
# avoid colliding with markdown-like patterns or sentinel angle-bracket
# constructs the writer might legitimately emit.
_MARKER_RE = re.compile(r"<\d{1,5}>")
# Back-to-back violation: a marker IMMEDIATELY followed (whitespace-only OK)
# by another marker. The lookahead keeps matches overlapping so that a run
# of N consecutive markers produces N-1 violations rather than ⌊N/2⌋ (which
# is what a non-lookahead `<…><…>` pattern returns under `findall`'s
# non-overlapping semantics). Accurate counts matter for the dev10 gate
# criterion (`marker-violation rate < 5%`).
_BACK_TO_BACK_RE = re.compile(r"<\d{1,5}>(?=\s*<\d{1,5}>)")
# Collapse runs of >=2 whitespace left after removing adjacent markers.
_DOUBLED_WS_RE = re.compile(r"[ \t]{2,}")

# Wave 0 §11: heading-line dot-number repair. Only touches lines whose first
# non-whitespace character is `#` so prose like "section 4 . 1 . 1" (rare,
# but possible in citation patterns) is not silently rewritten.
_HEADING_LINE_RE = re.compile(r"^[ \t]*#+[ \t].*$", re.MULTILINE)
# round 7 Fix A: full dotted-number token. CAPEL space-injection produces
# ASYMMETRIC, MULTI-LEVEL fragments like `6 .1`, `6. 1`, `7 .1 .1` (the dev6
# id-44 collapse — a `6.1` subsection became 1 of 36 fake H1 chapters because
# numbering_fix read the fragmented `6` as a chapter). The old
# `(\d+)\s+\.\s+(\d+)` required a space on BOTH sides AND collapsed one dot per
# pass, so it missed `6 .1` entirely and left `7.1 .1` half-fixed. This matches
# the WHOLE dotted-number run and strips its internal whitespace in one sub.
# `(?:...)+` requires a DIGIT after every dot, so `5 . Results`, a list-style
# `100. Item`, and version prose are never joined.
_FRAG_NUM_RE = re.compile(r"\d+(?:[ \t]*\.[ \t]*\d+)+")

# Wave 0 §11: word-fragment repair. The two-tier strategy is documented at
# `_repair_word_fragments` below. The stopword list blocks rejoins of
# legitimate short English word pairs — without it, "to be" → "tobe",
# "the cat" → "thecat", etc. List restricted to ≤5 chars (longer words
# would never match the length thresholds anyway) and to the high-frequency
# function-word + common-content-word vocabulary that BPE tokenizers leave
# intact (so they show up as standalone short tokens in prose).
_STOPWORDS: frozenset[str] = frozenset(
    {
        # 1-2 char
        "a",
        "i",
        "an",
        "as",
        "at",
        "be",
        "by",
        "do",
        "go",
        "he",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "no",
        "of",
        "on",
        "or",
        "so",
        "to",
        "up",
        "us",
        "we",
        # 3 char
        "all",
        "and",
        "any",
        "are",
        "but",
        "can",
        "did",
        "few",
        "for",
        "get",
        "had",
        "has",
        "her",
        "him",
        "his",
        "how",
        "its",
        "let",
        "may",
        "men",
        "new",
        "not",
        "now",
        "off",
        "old",
        "one",
        "our",
        "out",
        "own",
        "per",
        "put",
        "saw",
        "say",
        "see",
        "she",
        "the",
        "too",
        "top",
        "two",
        "use",
        "via",
        "was",
        "way",
        "who",
        "why",
        "yes",
        "yet",
        "you",
        # 4 char
        "also",
        "back",
        "been",
        "both",
        "came",
        "come",
        "does",
        "down",
        "each",
        "even",
        "ever",
        "from",
        "give",
        "good",
        "have",
        "here",
        "high",
        "into",
        "just",
        "know",
        "left",
        "like",
        "long",
        "made",
        "make",
        "many",
        "more",
        "most",
        "much",
        "must",
        "next",
        "none",
        "only",
        "over",
        "same",
        "seen",
        "such",
        "take",
        "than",
        "that",
        "them",
        "then",
        "they",
        "this",
        "time",
        "took",
        "very",
        "well",
        "went",
        "were",
        "what",
        "when",
        "will",
        "with",
        "your",
        # 5 char
        "about",
        "above",
        "after",
        "again",
        "being",
        "below",
        "could",
        "every",
        "first",
        "found",
        "great",
        "group",
        "house",
        "large",
        "later",
        "might",
        "never",
        "often",
        "other",
        "place",
        "right",
        "shall",
        "since",
        "small",
        "still",
        "their",
        "there",
        "these",
        "those",
        "three",
        "under",
        "until",
        "where",
        "which",
        "while",
        "world",
        "would",
        "young",
    }
)

# 3+ adjacent short alphabetic tokens. First may be capitalized OR all
# lowercase (proper nouns or content words); subsequent must be lowercase
# (BPE continuation pattern). Allows runs of 3-5 fragments — empirical
# patterns from id=91 smoke show `Sag itt arius` (3), `Kuru m ada` (3),
# `A ldebar an` (3), `ass ault ist` (3); 4-5 are rarer but possible.
#
# Negative-lookahead stopword guard: without it, the regex greedily
# matches `The ass ault` (3-piece run starting with stopword `The`),
# the callback returns the original (stopword guard), and re.sub
# advances past `ault`, so the legitimate `ass ault ist` run that
# starts AFTER `The` never gets a chance to match. The lookahead skips
# matches whose first piece is a stopword so re.sub can find the real
# fragment run further along. Case-insensitive so `The` matches `the`.
_STOPWORD_LOOKAHEAD_RE = "(?i:" + "|".join(sorted(map(re.escape, _STOPWORDS), key=len, reverse=True)) + r")\b"
_THREE_PLUS_RUN_RE = re.compile(rf"\b(?!{_STOPWORD_LOOKAHEAD_RE})[A-Za-z][a-z]{{0,4}}(?: [a-z]{{1,5}}){{2,4}}\b")

# 2-fragment Capital + lowercase pair. First piece is a short capitalized
# fragment (1-5 chars, single uppercase letter optionally followed by 1-4
# lowercase — id=91 patterns include single-letter starts like `K anon`
# → `Kanon`); second piece is a short lowercase fragment (2-5 chars).
# The `_repair_word_fragments` guard requires at least one piece be ≤2
# chars (BPE-characteristic shortness) to avoid joining legitimate proper
# noun + content word pairs like "Tax man" → "Taxman". The "i" / "a"
# stopwords block single-letter false positives like `I am` / `A few`.
_TWO_FRAG_CAP_LOWER_RE = re.compile(r"\b([A-Z][a-z]{0,4}) ([a-z]{2,5})\b")

# Vowels — used by the 2-piece rule to discriminate BPE-fragmented
# suffixes (`orpio`, `oga`, `anon`, `arius`) which typically begin with
# a vowel (because the BPE split point lands inside a syllable) from
# standalone short English content words (`wore`, `ran`, `man`, `lit`)
# which typically begin with a consonant.
_VOWELS = frozenset("aeiou")

# Wave 0.1 §11.7 (2026-05-26 smoke-validation follow-up): footnote-bracket
# whitespace repair. The 2026-05-26 post-Wave-0 id=91 smoke surfaced 47
# of 180 footnote markers in the form `[^S1-1 ]`, `[^ S8 -1 ]` — the
# writer subword-split the FOOTNOTE TOKEN itself across CAPEL markers
# (`[^<N>S1<N-1>-<N-2>1<N-3>]`), the strip removed the `<N>` tokens and
# left single spaces inside the brackets, and `footnote_normalize`'s
# inline-marker regex `\[\^([A-Za-z0-9._-]+)\]` rejected every such
# marker (whitespace is not in the token char class). Result: 47
# footnotes silently dropped + zero definition lines parsed + no
# References block in the article. The Wave 0 directive added `[^S1-3]`
# to the "ONE TOKEN" enumeration but the writer ignored it under
# retry-storm pressure. This repair pass is the safety net: strip ALL
# whitespace from inside `[^...]` brackets after marker strip.
_FOOTNOTE_BRACKET_RE = re.compile(r"\[\^([^\]]*)\]")


def _repair_heading_numbers(text: str) -> tuple[str, int]:
    """Repair fragmented heading numbers (`## 6 .1`, `## 6. 1`, `## 7 .1 .1`,
    `## 4 . 1 . 1`) → `## 6.1` / `## 7.1.1` / `## 4.1.1`.

    Restricted to lines starting with `#` so the rejoin can't silently rewrite a
    legitimate `4 . 1 . 1` pattern in prose. Matches the whole dotted-number run
    and strips its internal whitespace in a single sub (multi-level safe — the
    old one-dot-per-pass loop left asymmetric multi-level fragments half-fixed)."""
    n_fixed = 0

    def _collapse(m: re.Match) -> str:
        nonlocal n_fixed
        orig = m.group(0)
        joined = re.sub(r"[ \t]+", "", orig)
        if joined != orig:
            n_fixed += orig.count(".")  # ~dot-levels repaired (keeps telemetry semantics)
        return joined

    def _fix_line(match: re.Match) -> str:
        return _FRAG_NUM_RE.sub(_collapse, match.group(0))

    return _HEADING_LINE_RE.sub(_fix_line, text), n_fixed


def _repair_word_fragments(text: str) -> tuple[str, int]:
    """Conservatively rejoin BPE-subword fragments left by aggressive CAPEL.

    The writer occasionally treats CAPEL's "one content token per marker"
    directive at the BPE-subword level, so "Sagittarius" lands as three
    fragments `Sag itt arius` separated by single spaces (where the
    markers used to be). The strengthened `capel_directive` is the
    primary defense; this repair is a safety net for the cases where
    the writer ignores the directive.

    Two-tier strategy, applied in order (2-piece FIRST, then 3+):

    **2-fragment Capital + lowercase pair** (medium precision, runs first):
    a short capitalized fragment followed by a short lowercase fragment.
    Guarded by: at least one piece ≤2 chars (BPE-characteristic shortness),
    neither in `_STOPWORDS`, joined ≥5 chars. Catches `Sc orpio`,
    `Hy oga`, `Lib ra`, `K anon`, `Cl oth`, `Cygn us`. Running 2-piece
    BEFORE 3+ means proper-noun fragments adjacent to legitimate short
    content words get joined cleanly (e.g. `Sc orpio sign rules` →
    `Scorpio sign rules`, not `Scorpiosignrules`). The ≤2-char
    requirement blocks legitimate pairs like "Tax man" (3+3) from being
    joined.

    **3+ adjacent short tokens** (high precision when joined-length is
    in the typical real-word band): runs of 3-5 adjacent alphabetic
    tokens, each ≤5 chars, none in `_STOPWORDS`, joined length in
    [8, 12] chars (the empirical band that real BPE-fragmented English
    words live in: Sagittarius=11, Kurumada=8, assaultist=10,
    Encyclopedia=12), only first capitalized. The upper bound blocks
    runs of 4+ legitimate short content words from being joined into
    impossibly long pseudo-compounds (e.g. `Mu ran away fast` joins
    to a 13-char pseudo-compound and is correctly skipped).

    **Known limitations** (acceptable because the directive is the
    primary defense):
      - Lowercase 2-piece content-word fragments like `calibr ated`
        not caught (2-piece rule requires capitalized first piece).
      - Real words >12 chars when joined not caught (rare —
        `Constellation`=13 misses).
      - 2-piece fragments where the second piece collides with a
        stopword not caught (`Cygn us` blocked because `us` is a
        stopword).
      - Middle pieces >5 chars not caught (`A ldebar an` — middle
        piece `ldebar` is 6 chars).
      - Synthetic adjacency of 3 short non-stopword content words
        with joined length in [8, 12] would false-positively join.
        In real prose this is rare; in CAPEL-fragmented text the
        directive eliminates the upstream cause.
    """
    n_repairs = 0

    def _fix_pair(match: re.Match) -> str:
        nonlocal n_repairs
        a, b = match.group(1), match.group(2)
        if a.lower() in _STOPWORDS or b in _STOPWORDS:
            return f"{a} {b}"
        if len(a) > 2 and len(b) > 2:
            return f"{a} {b}"
        joined = a + b
        if len(joined) < 5:
            return f"{a} {b}"
        # Consonant-start guard on the second piece, gated on ≥3-char
        # length. BPE-fragmented suffixes (`orpio`, `oga`, `anon`,
        # `arius`) typically start with a vowel because the subword
        # split lands inside a syllable; standalone short English
        # content words (`wore`, `ran`, `man`, `lit`, `set`) typically
        # start with a consonant. Without this guard, `Mu wore` →
        # `Muwore` (Saint Seiya proper noun + verb falsely joined).
        #
        # Why ≥3-char gate (Greptile PR #28 follow-up): 2-char suffixes
        # bypass this guard unconditionally. The bypass is intentional
        # and load-bearing — `Lib ra` → `Libra` requires it (`ra` is
        # 2-char consonant-start, blocked if the guard fired). The
        # bypass is safe in practice because the 2-char-consonant-start
        # non-stopword vocabulary is vanishingly small in English (no
        # `ns`, `rs`, `ts` etc. exist as standalone words; the
        # stopword-eligible `we`, `me`, `he`, `be`, `do`, `go`, `no`,
        # `so`, `to`, `by` are already blocked by the stopword check
        # above). Synthetic false positives like `Cap nd` → `Capnd`
        # remain theoretically possible but require a non-stopword
        # 2-char consonant-start suffix that does not exist as a real
        # English word — encountered only in adversarial inputs.
        if len(b) >= 3 and b[0] not in _VOWELS:
            return f"{a} {b}"
        n_repairs += 1
        return joined

    text = _TWO_FRAG_CAP_LOWER_RE.sub(_fix_pair, text)

    def _fix_run(match: re.Match) -> str:
        nonlocal n_repairs
        run = match.group(0)
        parts = run.split()
        # Stopword filter — the regex's negative lookahead only blocks
        # FIRST-piece stopwords; trailing-piece stopwords (e.g. `the` /
        # `and` / `was` in middle or final position) still need to be
        # caught here. The alphabetic-only / ≤5-char / lowercase-suffix
        # properties Greptile flagged are already enforced by
        # `_THREE_PLUS_RUN_RE` itself (first piece `[A-Za-z][a-z]{0,4}`,
        # subsequent `[a-z]{1,5}`); the redundant guards were removed in
        # the PR #28 Greptile follow-up.
        if any(p.lower() in _STOPWORDS for p in parts):
            return run
        joined = "".join(parts)
        # Joined-length band [8, 12] is the empirical sweet spot for real
        # BPE-fragmented English words (Sagittarius=11, Kurumada=8,
        # assaultist=10, Encyclopedia=12). 13+ chars typically indicates a
        # false-positive run of adjacent short content words (synthetic
        # case: `Mu ran away fast` joins to a 13-char pseudo-compound).
        if len(joined) < 8 or len(joined) > 12:
            return run
        n_repairs += 1
        return joined

    text = _THREE_PLUS_RUN_RE.sub(_fix_run, text)

    return text, n_repairs


def _repair_footnote_brackets(text: str) -> tuple[str, int]:
    """Strip whitespace inside `[^...]` brackets left by CAPEL subword
    fragmentation of the footnote token (Wave 0.1 §11.7).

    The writer sometimes treats footnote markers like `[^S1-3]` as
    multiple "content tokens" and interleaves CAPEL markers between the
    bracket contents — producing post-strip output like `[^ S8 -1 ]`,
    `[^S1-1 ]`. `footnote_normalize`'s inline-marker regex requires the
    inner token to match `[A-Za-z0-9._-]+` (no whitespace), so a single
    space inside the brackets makes the marker invisible to normalize
    and the footnote is silently dropped — destroying the entire
    References block downstream (verified on the 2026-05-26 id=91
    post-Wave-0 smoke: 47 of 180 markers broken, 0 def lines parsed).

    Conservative: only strips whitespace INSIDE `[^...]` brackets;
    leaves the surrounding text alone. The inner content may legitimately
    contain `[A-Za-z0-9._-]` characters (matching the normalize token
    char class). Anything else inside the brackets is whitespace OR a
    rendering artifact — both safe to remove.
    """
    n_repairs = 0

    def _fix(match: re.Match) -> str:
        nonlocal n_repairs
        inner = match.group(1)
        cleaned = re.sub(r"\s+", "", inner)
        if cleaned == inner:
            return match.group(0)
        n_repairs += 1
        return f"[^{cleaned}]"

    return _FOOTNOTE_BRACKET_RE.sub(_fix, text), n_repairs


def strip_capel_markers(text: str) -> tuple[str, dict]:
    """Strip CAPEL markers from writer output.

    Returns (stripped_text, stats):
        n_markers_stripped: total markers removed.
        n_violations: count of back-to-back marker positions (no intervening
            content token). Overlap-aware: `<5><4><3>` reports 2 violations.
        n_word_repairs: count of word-fragment rejoins performed by the
            §11 safety-net repair pass. Non-zero means the writer was
            subword-splitting and the post-process caught some — directive
            compliance is the upstream lever.
        n_heading_repairs: count of dotted heading-number rejoins performed
            by the §11 safety-net repair pass.
    """
    zero_stats = {
        "n_markers_stripped": 0,
        "n_violations": 0,
        "n_word_repairs": 0,
        "n_heading_repairs": 0,
        "n_bracket_repairs": 0,
    }
    if not text:
        return text, zero_stats
    n_violations = len(_BACK_TO_BACK_RE.findall(text))
    # Replace each marker with a single space — handles `the<899>quick`
    # (no surrounding whitespace) without gluing the words together.
    stripped, n_stripped = _MARKER_RE.subn(" ", text)
    if not n_stripped:
        # No markers present — return original text verbatim so legitimate
        # double-spaces (rare but possible in code blocks, indented quotes)
        # survive untouched AND the §11 repair passes don't run on text
        # that never went through the CAPEL bug path.
        return text, {**zero_stats, "n_violations": n_violations}
    # Only collapse whitespace runs that THIS strip introduced.
    stripped = _DOUBLED_WS_RE.sub(" ", stripped)
    # §11 repairs run AFTER marker strip and whitespace collapse, only
    # when markers were actually present. This preserves the no-markers
    # contract above.
    stripped, n_heading_repairs = _repair_heading_numbers(stripped)
    stripped, n_word_repairs = _repair_word_fragments(stripped)
    stripped, n_bracket_repairs = _repair_footnote_brackets(stripped)
    return stripped, {
        "n_markers_stripped": n_stripped,
        "n_violations": n_violations,
        "n_word_repairs": n_word_repairs,
        "n_heading_repairs": n_heading_repairs,
        "n_bracket_repairs": n_bracket_repairs,
    }
