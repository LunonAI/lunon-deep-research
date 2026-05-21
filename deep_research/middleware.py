"""Engine robustness middleware (p1-checklist item 9).

Four model-agnostic wrappers adapted from AI-Q custom_middleware.py (the 4 P1
picks per p1:28). We don't run a LangChain agent loop, so these are applied as
explicit helpers at the pipeline integration points:

1. sanitize_role  — ToolNameSanitization: snap a hallucinated specialist/type
   name to the nearest valid one.
2. reasoning_aware_json — EmptyResponseRetry + reasoning-aware: detect failure
   patterns (empty / refusal / unparseable) and retry with a corrective nudge.
3. BudgetGuard — ToolCallBudget: hard cap; raises when exceeded.
4. validate_report — ReportValidation: terminal length/structure/truncation
   check; returns (ok, reasons) so the caller can nudge continuation.
"""
import difflib
import re

VALID_SPECIALISTS = ["evidence_gatherer", "mechanism_explorer", "comparator",
                      "critic", "horizon_scanner", "generalist"]
VALID_QTYPES = ["factual", "causal", "comparative", "critical", "trend"]

_TRUNC_MARKERS = ("...", "[truncated", "TODO", "TBD", "placeholder",
                   "lorem ipsum", "<continue", "to be completed", "（待补充）",
                   "未完待续", "[continued]")


def sanitize_role(name: str, valid=None) -> str:
    valid = valid or VALID_SPECIALISTS
    n = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if n in valid:
        return n
    m = difflib.get_close_matches(n, valid, n=1, cutoff=0.5)
    return m[0] if m else valid[-1]  # default = generalist / last


def sanitize_qtype(t: str) -> str:
    return sanitize_role(t, VALID_QTYPES)


class BudgetGuard:
    """ToolCallBudget middleware: hard cap on tool calls."""

    def __init__(self, budget: int):
        self.budget = budget
        self.used = 0

    def can(self, n: int = 1) -> bool:
        return self.used + n <= self.budget

    def spend(self, n: int = 1):
        self.used += n
        if self.used > self.budget:
            raise RuntimeError(
                f"tool-call budget exceeded ({self.used}>{self.budget})")

    @property
    def remaining(self):
        return max(0, self.budget - self.used)


def reasoning_aware_json(call_json_fn, role, user, system, *, max_tokens,
                         note, tries=3, **kw):
    """EmptyResponseRetry: retry an LLM JSON call with a corrective nudge when
    the output is empty/refusal/unparseable (detected failure pattern)."""
    last = None
    nudge = ""
    for i in range(tries):
        try:
            return call_json_fn(role, user + nudge, system=system,
                                max_tokens=max_tokens, note=note, **kw)
        except Exception as e:  # noqa: BLE001
            last = e
            nudge = ("\n\n[RETRY] Your previous reply was empty or not valid "
                     "JSON. Output ONLY the required JSON object, no prose, "
                     "no code fences.")
    raise RuntimeError(f"reasoning_aware_json({role}) failed: {last}")


def validate_report(text: str, *, min_words: int = 1200):
    """ReportValidation: terminal length / structure / truncation check."""
    reasons = []
    words = len(re.findall(r"\S+", text or ""))
    if words < min_words:
        reasons.append(f"too short ({words} words < {min_words})")
    if not re.search(r"^#{1,3}\s", text or "", re.M) and "**" not in (text or ""):
        reasons.append("no headings/structure")
    tail = (text or "")[-400:].lower()
    if any(m.lower() in tail for m in _TRUNC_MARKERS):
        reasons.append("ends on a truncation/placeholder marker")
    low = (text or "").lower()
    if any(m.lower() in low for m in ("lorem ipsum", "[placeholder", "tbd]",
                                      "（待补充）")):
        reasons.append("contains placeholder text")
    return (not reasons), reasons
