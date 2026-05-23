"""WebWeaver memory bank (p1-checklist items 13, 25; arXiv 2509.13312).

Citation-ID-keyed evidence store. Researcher specialists write evidence blocks
in (isolated context); the writer retrieves PER SECTION by citation ID only —
never the full corpus. This is the context-engineering boundary for the writer
(item 25): writer.context = outline + only the cited evidence for the section.

Each block: {eid 'E12', source_name, url, title, text, query_id, section_ids,
specialist, language}. Section→evidence is via the Architect query's
target_sections (the query that produced the evidence).

P2-Wave-1-B (2026-05-22): adds primary-section tagging + `for_section_pruned()`
mode-aware retrieval. When `DR_WEBWEAVER != "off"`, each eid carries a
deterministic `primary_section_id` and non-primary cross-cutting evidence is
either replaced with a placeholder (soft / serial) or omitted (hard) when
returned by `for_section_pruned()`. See `docs/research_findings_v2.md` §B2 and
the WAVE1_DESIGN.md design doc.
"""

import re

# Token-overlap heuristic helpers — used by `assign_primary_sections()`.
# Conservative stop-list: very common English + Chinese punctuation glyphs.
# CJK tokens (>=2 chars after splitting) survive because `\w+` matches Unicode
# word chars by default in Python's `re` module.
_STOP_TOKENS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "and",
    "or",
    "but",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "may",
    "might",
    "can",
    "this",
    "that",
    "these",
    "those",
    "with",
    "by",
    "from",
    "as",
    "if",
    "than",
    "such",
    "into",
    "via",
    "per",
    "也",
    "和",
    "或",
    "及",
    "与",
    "之",
    "的",
    "了",
    "在",  # ZH common particles
}


def _tokenize(s: str) -> set[str]:
    """Lowercase, split on non-word, drop short tokens and stop-words.
    Returns set for fast intersection. Idempotent. ASCII + CJK aware (since
    Python `\\w` matches Unicode word chars by default)."""
    if not s:
        return set()
    tokens = re.findall(r"\w+", s.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOP_TOKENS}


def _section_keywords(toc_entry: dict) -> set[str]:
    """Concatenated title + subsection titles → token set."""
    parts = [toc_entry.get("title", "") or ""]
    for sub in toc_entry.get("subsections", []) or []:
        if isinstance(sub, str):
            parts.append(sub)
        elif isinstance(sub, dict):
            parts.append(sub.get("title", "") or "")
    return _tokenize(" ".join(parts))


class MemoryBank:
    def __init__(self):
        self._items = {}  # eid -> block
        self._by_section = {}  # section_id -> [eid]
        self._n = 0
        self._primary_assigned = False  # idempotency guard for assign_primary_sections

    def add(self, *, source_name, url, title, text, query_id, section_ids, specialist, language) -> str:
        self._n += 1
        eid = f"E{self._n}"
        block = {
            "eid": eid,
            "source_name": (source_name or "").strip(),
            "url": url or "",
            "title": (title or "").strip(),
            "text": (text or "").strip(),
            "query_id": query_id,
            "section_ids": list(section_ids or []),
            "specialist": specialist,
            "language": language,
        }
        self._items[eid] = block
        for sid in block["section_ids"]:
            self._by_section.setdefault(sid, []).append(eid)
        return eid

    def get(self, eids):
        return [self._items[e] for e in eids if e in self._items]

    def for_section(self, section_id, max_blocks=40):
        """Evidence whose producing query targeted this section (or a parent)."""
        eids = list(self._by_section.get(section_id, []))
        # also include evidence targeting the top-level parent (e.g. S1 for S1.2)
        parent = section_id.split(".")[0]
        if parent != section_id:
            eids += [e for e in self._by_section.get(parent, []) if e not in eids]
        return self.get(eids[:max_blocks])

    def assign_primary_sections(self, plan: dict) -> None:
        """Assign one `primary_section_id` to every block, in-place.

        For each eid with `len(section_ids) == 1`, primary is that sole sid.
        For multi-section eids, primary is the candidate sid with the highest
        token-overlap score between the eid's `text + source_name` and the
        section's `title + subsection titles`. Ties broken by first occurrence
        in `plan["report_toc"]`.

        DETERMINISTIC and idempotent. Safe to call multiple times. Must be
        invoked ONCE before `for_section_pruned()` is used in any mode other
        than "off".

        The mutation is restricted to adding `primary_section_id` to each
        existing block — no eid or section_id field is changed. Callers that
        had earlier called `for_section()` with a particular block continue
        to see the same evidence (the WebWeaver layer reads
        `primary_section_id` lazily).
        """
        toc = plan.get("report_toc", []) or []
        sid_order = {(s.get("id") or ""): i for i, s in enumerate(toc) if s.get("id")}
        section_tokens = {(s.get("id") or ""): _section_keywords(s) for s in toc if s.get("id")}

        for _eid, block in self._items.items():
            sids = block.get("section_ids", []) or []
            if not sids:
                block["primary_section_id"] = None
                continue
            if len(sids) == 1:
                block["primary_section_id"] = sids[0]
                continue
            eid_text = (block.get("text", "") or "") + " " + (block.get("source_name", "") or "")
            eid_tok = _tokenize(eid_text)
            best_sid: str | None = None
            best_score = -1
            best_rank = len(sid_order) + 1  # higher = lower priority
            for sid in sids:
                sect_tok = section_tokens.get(sid, set())
                score = len(eid_tok & sect_tok) if (eid_tok and sect_tok) else 0
                rank = sid_order.get(sid, len(sid_order))
                # Higher score wins. Tie → earlier-in-TOC wins (smaller rank).
                if (score > best_score) or (score == best_score and rank < best_rank):
                    best_sid = sid
                    best_score = score
                    best_rank = rank
            block["primary_section_id"] = best_sid
        self._primary_assigned = True

    def for_section_pruned(self, section_id, max_blocks: int = 40, mode: str = "off") -> list[dict]:
        """Mode-aware variant of `for_section()`.

        Modes:
            ``off``      — identical to `for_section()` (legacy path).
            ``soft``     — primary-tagged entries returned in full; non-primary
                           cross-cutting entries returned as compact placeholders
                           `{eid, source_name, placeholder: True, primary_section_id}`
                           with no `text`, no `url`, no `title`.
            ``serial``   — same evidence semantics as `soft`. Distinct name lets
                           the orchestrator path select serial vs parallel writes.
            ``hard``     — non-primary cross-cutting entries OMITTED entirely.

        An eid is "primary for `section_id`" iff its `primary_section_id`
        equals `section_id` OR equals the parent sid (e.g. eid primary to "1"
        is primary for "1.1"). Sibling-primary eids (e.g. primary to "1.2"
        when fetched for "1.1") are placeholders / omitted per mode.

        If `assign_primary_sections()` has not been called, falls back to
        `for_section()` regardless of mode (defensive — never crashes).
        """
        if mode == "off" or not self._primary_assigned:
            return self.for_section(section_id, max_blocks)

        # Recompute the same eid-set `for_section()` would return.
        eids = list(self._by_section.get(section_id, []))
        parent = section_id.split(".")[0]
        if parent != section_id:
            eids += [e for e in self._by_section.get(parent, []) if e not in eids]
        eids = eids[:max_blocks]

        out = []
        for e in eids:
            b = self._items.get(e)
            if b is None:
                continue
            primary = b.get("primary_section_id")
            # "Primary for this section" ⇔ primary == this sid OR primary == parent
            is_primary = primary == section_id or (parent != section_id and primary == parent)
            if is_primary or primary is None:
                out.append(b)
                continue
            if mode == "hard":
                continue
            # soft / serial: placeholder block (no text/url/title)
            out.append(
                {
                    "eid": b["eid"],
                    "source_name": b["source_name"],
                    "url": "",
                    "title": "",
                    "text": "",
                    "placeholder": True,
                    "primary_section_id": primary,
                }
            )
        return out

    def all_blocks(self):
        return list(self._items.values())

    def stats(self):
        return {"n_evidence": len(self._items), "n_sections_with_evidence": len(self._by_section)}

    def source_table(self):
        """De-duplicated {url -> {n, source_name, title}} for the writer's
        cleaning-resistant inline attribution (item 19)."""
        out, i = {}, 0
        for b in self._items.values():
            if b["url"] and b["url"] not in out:
                i += 1
                out[b["url"]] = {"n": i, "source_name": b["source_name"], "title": b["title"]}
        return out
