"""WebWeaver memory bank (p1-checklist items 13, 25; arXiv 2509.13312).

Citation-ID-keyed evidence store. Researcher specialists write evidence blocks
in (isolated context); the writer retrieves PER SECTION by citation ID only —
never the full corpus. This is the context-engineering boundary for the writer
(item 25): writer.context = outline + only the cited evidence for the section.

Each block: {eid 'E12', source_name, url, title, text, query_id, section_ids,
specialist, language}. Section→evidence is via the Architect query's
target_sections (the query that produced the evidence).
"""


class MemoryBank:
    def __init__(self):
        self._items = {}  # eid -> block
        self._by_section = {}  # section_id -> [eid]
        self._n = 0

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
