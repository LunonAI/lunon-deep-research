"""role_play node (p1-checklist item 32; LINK-Researcher pipeline node 1).

Runs after intent.py, before scout. Opus 4.7 generates a one-paragraph expert
persona (60-200 words) for the task given (prompt, domain, archetype,
language). The persona is injected as a PREPENDED context block in the
architect's system prompt and is available to the writer system prompt.

Verified by: persona length 60-200 words; persona reflects domain (e.g.,
Finance → "senior buy-side equity analyst..." NOT "generic researcher").
"""

from dataclasses import dataclass

from .. import llm
from ..node_wrap import node


@dataclass
class RolePlayInput:
    query: str
    language: str
    archetype: str
    domain: str


@dataclass
class RolePlayOutput:
    persona: str


_SYSTEM = (
    "You write a one-paragraph EXPERT PERSONA for a deep-research analyst who "
    "will answer the given prompt. Output ONLY the persona prose (no preface, "
    "no bullets, no JSON), 80-180 words, in the prompt's language. The persona "
    "MUST be specific to the task's domain and archetype — name the analytical "
    "tradition, the data sources this expert habitually consults, the framing "
    "they typically adopt, and the standards of rigour they hold to. E.g. for "
    "a Finance/predict prompt: 'a senior buy-side equity analyst with 12+ "
    "years of insurance-sector coverage; reads 10-Ks and SOA reports cover-to-"
    "cover; frames every outlook with sensitivity ranges and named drivers...'. "
    "Avoid generic 'thorough researcher who cares about accuracy' filler."
)


@node("role_play")
def run(inp: RolePlayInput) -> RolePlayOutput:
    user = (
        f"Prompt language: {inp.language}\nDomain: {inp.domain}\n"
        f"Archetype: {inp.archetype}\n\nPROMPT:\n{inp.query}\n\n"
        "Write the persona."
    )
    for attempt in range(2):
        txt = llm.call("architect", user, system=_SYSTEM, max_tokens=900, effort="low", note=f"role_play.{attempt}")
        words = len(txt.split())
        if words >= 60:
            return RolePlayOutput(persona=txt.strip())
        # too short — retry once with an explicit length requirement
        user = (
            user + f"\n\n[RETRY] Your previous reply was {words} words — "
            "WELL BELOW the 80-180 word REQUIREMENT. Write the FULL "
            "persona paragraph now, 80-180 words, NO preface, NO bullets."
        )
    return RolePlayOutput(persona=txt.strip())
