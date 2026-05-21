"""Claude Opus 4.7 client (anthropic SDK), mirroring gpt55.py's retry +
auto cost-log discipline. Used for orchestrator/planner/scout/architect/writer.

Cost hook: Anthropic usage shape (input_tokens/output_tokens) is logged via
track.log_usage, which already accepts that shape (track.py:57-58).
"""
import time

import anthropic

from .._env import get, log_usage

_KEY = get("ANTHROPIC_API_KEY")
_BASE = get("ANTHROPIC_BASE_URL") or None  # SDK default if empty

_client = anthropic.Anthropic(api_key=_KEY, **({"base_url": _BASE} if _BASE else {}))

_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


def raw_call(model, user, system="", max_tokens=8000, think=False,
             effort="low", max_retries=3, note=""):
    """Return (text_str, usage_dict). Raises RuntimeError after retries.

    Opus 4.7 API: reasoning is controlled by output_config.effort; think=True
    enables adaptive thinking (thinking.type='adaptive'). Default: plain (no
    thinking) to control cost. (The old thinking.type='enabled'+budget_tokens
    form is rejected by Opus 4.7.)
    """
    if not _KEY:
        raise RuntimeError("ANTHROPIC_API_KEY missing from .env")
    kw = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kw["system"] = system
    if think:
        kw["thinking"] = {"type": "adaptive"}
        kw["output_config"] = {"effort": effort}
    last = ""
    for attempt in range(max_retries):
        try:
            resp = _client.messages.create(**kw)
        except _RETRYABLE as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(2 ** attempt * 3, 45))
            continue
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 504, 529):
                last = f"HTTP {e.status_code}"
                time.sleep(min(2 ** attempt * 3, 45))
                continue
            raise RuntimeError(f"Anthropic HTTP {e.status_code}: {str(e)[:400]}")
        u = resp.usage
        # Capture full Anthropic usage shape — including cache_* fields which
        # bill at 1.25× input (cache_creation) and 0.1× input (cache_read).
        # Currently 0 since we don't use cache_control, but forward-safe.
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        log_usage(model, usage, note=note or "claude")
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        if text:
            return text, usage
        last = f"empty content (stop={resp.stop_reason})"
        kw["max_tokens"] = min(int(kw["max_tokens"] * 1.6), 32000)
    raise RuntimeError(f"Anthropic {model} failed after {max_retries} retries: {last}")
