"""Typed pipeline state (p1-checklist item 36; LINK-Researcher graph-as-contract
pattern, adapted without LangGraph).

Each pipeline node exports a typed input + output dataclass and a `run(input)
-> output` entrypoint. The sequencer (orchestrate.pipeline) threads a single
PipelineState through the graph, calling each node with the subset it needs
and merging the typed output back into state. State passing is by typed
dataclasses, not loose kwargs.
"""

from dataclasses import dataclass, field
from typing import Any


# ---- DesignGuide (consumed by writer, refiner, zh_writer_pass, validation) ----
@dataclass
class DesignGuide:
    """Stylistic + structural conventions for one report (item 33).

    Content is derived from p0_artifacts/judge_preferences.md — the actual
    GPT-5.5 judge target — NOT from LINK-Researcher's stylistic defaults.
    """

    section_numbering: str = "1.1.1"  # "1.", "1.1", "1.1.1" | "I./A./1." | "none"
    citation_format: str = "inline-source-name"  # locked from cleaner_behavior.md
    citation_instruction: str = ""  # full verbal directive
    terminology: dict = field(default_factory=dict)  # ambiguous-term → preferred
    transitions_register: str = "analytical"  # analytical | technical | predictive | comparative
    header_depth_max: int = 3  # 4 for technical-deep archetypes
    tone_register: str = "analytical"  # forward-looking | causal | comparative | etc.
    table_use: str = "comparison-when-multi-entity"  # judge rewards entity×dimension matrices
    zh_register_markers: list = field(default_factory=list)
    rewards_directives: list = field(default_factory=list)  # from judge_preferences rewards
    penalties_directives: list = field(default_factory=list)  # from judge_preferences penalties

    def as_writer_block(self) -> str:
        """Render as a writer/refiner system-prompt directive block."""
        parts = [
            f"SECTION NUMBERING: {self.section_numbering}",
            f"HEADER DEPTH MAX: {self.header_depth_max}",
            f"TONE REGISTER: {self.tone_register}",
            f"TRANSITIONS REGISTER: {self.transitions_register}",
            f"TABLE USE: {self.table_use}",
            self.citation_instruction or "",
        ]
        if self.terminology:
            parts.append(
                "TERMINOLOGY (use the preferred term consistently): "
                + "; ".join(f"{k}→{v}" for k, v in self.terminology.items())
            )
        if self.zh_register_markers:
            parts.append("ZH REGISTER MARKERS (use natively, do not translate): " + ", ".join(self.zh_register_markers))
        if self.rewards_directives:
            parts.append("JUDGE REWARDS — DO THESE:\n- " + "\n- ".join(self.rewards_directives))
        if self.penalties_directives:
            parts.append("JUDGE PENALTIES — AVOID THESE:\n- " + "\n- ".join(self.penalties_directives))
        return "\n\n".join(p for p in parts if p)


# ---- Scaffold (consumed by writer + validation) ----
@dataclass
class ScaffoldSection:
    section_id: str
    title: str
    subsections: list = field(default_factory=list)
    expected_length_tokens: int = 1200
    assigned_specialists: list = field(default_factory=list)  # role names
    placeholder: str = ""


@dataclass
class Scaffold:
    """Structural layout of the report (item 34) — distinct from the Architect
    plan (which plans what to research). The writer fills this scaffold; the
    validator checks against it."""

    sections: list = field(default_factory=list)  # list[ScaffoldSection]
    total_target_tokens: int = 12000

    def section_ids(self) -> list:
        return [s.section_id for s in self.sections]


# ---- PipelineState (composite, threaded through the graph) ----
@dataclass
class PipelineState:
    query: str
    language: str
    archetype: dict = field(default_factory=dict)
    domain: str = "default"
    intents: list = field(default_factory=list)
    persona: str = ""  # role_play output
    landscape: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)
    coverage_obligations: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    design_guide: DesignGuide | None = None
    scaffold: Scaffold | None = None
    memory_bank: Any = None
    digest: str = ""
    tool_calls: int = 0
    opening: str = ""
    sections: list = field(default_factory=list)  # list[str]
    section_scores: list = field(default_factory=list)
    failing_rationales: list = field(default_factory=list)
    article: str = ""
    validation_log: list = field(default_factory=list)
    refiner_passes: int = 0
    # Deterministic post-edit telemetry (numbering_fix module, plan v3 §2a+2d+2c)
    numbering_fix_stats: dict = field(default_factory=dict)
    # ART-style refiner gate verdict (plan v3 §3b, Branch B monitor-mode)
    refiner_gate_verdict: dict = field(default_factory=dict)
    # P2-Wave-1-D: evidence-layer dedup stats {mode, n_before, n_after,
    # d4_collapsed, d4_clusters, d1_collapsed?, d1_eids_embedded?, d1_error?}
    evidence_dedup_stats: dict = field(default_factory=dict)
    # P2-Wave-2: task id from the harness (used by G's W9-readability cache
    # for fragile-density conditional dedup-rule suppression). None means the
    # caller did not provide it (smoke runs, unit tests) — G silently no-ops.
    task_id: int | None = None
    # P2-Wave-2-A (CAPEL): per-section marker-stripping telemetry.
    # {section_id: {n_markers_stripped, n_violations}}.
    capel_stats: dict = field(default_factory=dict)
    # P2-Wave-2-G: True when the W9-readability fragile-density heuristic
    # auto-suppressed `_DEDUP_RULE` for this task. Decision is task-level
    # (archetype + W9 read score), not per-section, so a single bool suffices.
    g_dedup_suppressed: bool = False
    # Wave 1 §7.1 (2026-05-26): per-task count of specialist-call wall-
    # clock timeouts the orchestrator's `_research_with_timeout` wrapper
    # caught. Populated from `orchestrator.run` return dict (added in
    # PR #26 reliability layer). Pre-Wave-1 the field lived only on the
    # orchestrator's local return — never surfaced into drift telemetry,
    # so dev4 / W13 analysers couldn't correlate timeout pressure with
    # quality drift. 0 = clean run; > 0 = some specialist hit the
    # `_SPECIALIST_TIMEOUT_S` cap and the orchestrator fell back to
    # whatever partial content was available.
    n_specialist_timeouts: int = 0
    # Wave 1 §7.2 (2026-05-26): per-task footnote_normalize stats dict.
    # Populated from FootnoteNormalizeOutput at end of pipeline; the
    # `_persist_drift` writer adds a derived `inline_def_ratio` field
    # before logging so analysers can spot "writer is making fresh marker
    # per cite, no reuse" failure mode without computing the ratio every
    # time downstream.
    footnote_normalize_stats: dict = field(default_factory=dict)
    # P3-W4 (2026-05-27): per-task mermaid_validate stats dict
    # {n_blocks_found, n_blocks_valid, n_blocks_markdown_stripped,
    # n_blocks_fence_repaired, n_blocks_stripped_invalid_type}.
    # Populated from mermaid_validate.repair() in the post-pass chain;
    # forwarded into inner_loop_drift.jsonl so dev4 / W13 analysers can
    # track per-archetype mermaid emission rates and repair pressure.
    mermaid_validate_stats: dict = field(default_factory=dict)
    # P3-W3.b (2026-05-27): per-task xref_repair stats dict
    # {templates_repaired, dangling_refs_rewritten, sentences_deleted}.
    # Populated from pipeline.xref_repair.repair() in the post-pass chain
    # (orchestrate.py between zh_writer_pass and mermaid_validate). The
    # in-prompt `_MID_PARAGRAPH_XREF_RULE` directive is the primary force
    # producing clean cross-refs; this post-pass is the safety net that
    # catches "Building on §X" template regressions + dangling forward-
    # refs the writer occasionally emits. All-zero stats indicate clean
    # writer output; non-zero stats let dev4 / W13 analysers quantify
    # how often the safety net fires.
    xref_repair_stats: dict = field(default_factory=dict)
    # P3b-OPT2 (2026-05-27): per-section inner-loop iteration trajectory.
    # One entry per section: {"section": sid, "iters": [{"i", "grounding_ok",
    # "scored", "score_ok", "min_score"}, ...]}. INNER_CAP is unchanged (3);
    # this records WHETHER the 2nd/3rd corrective pass flipped a section from
    # failing to passing, so scripts/inner_cap_ab_analysis.py can decide
    # empirically whether cap=2 is safe without a paired A/B run. Pure
    # observation — no behavior change.
    inner_loop_trajectory: list = field(default_factory=list)
