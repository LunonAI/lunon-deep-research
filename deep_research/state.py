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
