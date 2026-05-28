"""P3b-OPT1 (2026-05-27): writer system-prompt caching tests.

The writer's 27.5 KB system prompt is byte-identical across every writer.sec
call within a task. Attaching an Anthropic prompt-cache breakpoint to the
system block lets the first call pay cache_creation (1.25x input) and the rest
read at 0.1x. Caching is output-invariant — the model receives identical
tokens whether the block is cached or not — so these tests assert the request
*structure*, never output behavior.
"""

from deep_research.clients import anthropic_client


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeUsage:
    def __init__(self):
        self.input_tokens = 100
        self.output_tokens = 50
        self.cache_creation_input_tokens = 80
        self.cache_read_input_tokens = 0


class _FakeMsg:
    def __init__(self):
        self.content = [_FakeBlock("hello")]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"


class _FakeStream:
    def __init__(self, captured_kw):
        self._captured = captured_kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return _FakeMsg()


def _patch_stream(monkeypatch):
    """Patch the SDK stream entry point; return a list that captures the kw
    dict each call was made with."""
    captured = []

    def fake_stream(**kw):
        captured.append(kw)
        return _FakeStream(captured)

    # Ensure the API-key guard passes even if .env is absent in CI.
    monkeypatch.setattr(anthropic_client, "_KEY", "test-key", raising=False)
    monkeypatch.setattr(anthropic_client._client.messages, "stream", fake_stream)
    return captured


def test_raw_call_default_no_cache_control(monkeypatch):
    """Default cache_system=False → system passed as a plain string, no
    cache_control structure anywhere in the request."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "u", system="SYS", note="t")
    assert len(captured) == 1
    assert captured[0]["system"] == "SYS", "system should be a bare string when caching off"


def test_raw_call_with_cache_system_wraps_system(monkeypatch):
    """cache_system=True → system reformatted as a list with a cache_control
    breakpoint on the text block."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "u", system="SYS", note="t", cache_system=True)
    sysblock = captured[0]["system"]
    assert isinstance(sysblock, list) and len(sysblock) == 1, f"expected list-of-one, got {sysblock!r}"
    assert sysblock[0]["type"] == "text"
    assert sysblock[0]["text"] == "SYS"
    assert sysblock[0]["cache_control"]["type"] == "ephemeral"


def test_raw_call_default_ttl_is_bare_5m_form(monkeypatch):
    """Default cache_ttl='5m' uses the GA bare {"type": "ephemeral"} form with
    NO ttl field — avoids any extended-cache beta-header dependency."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "u", system="SYS", cache_system=True)
    cc = captured[0]["system"][0]["cache_control"]
    assert "ttl" not in cc, f"5m form must omit ttl; got {cc!r}"


def test_raw_call_1h_ttl_sets_ttl_field(monkeypatch):
    """cache_ttl='1h' attaches the extended-TTL field for callers who batch
    with longer idle gaps."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "u", system="SYS", cache_system=True, cache_ttl="1h")
    cc = captured[0]["system"][0]["cache_control"]
    assert cc.get("ttl") == "1h"


def test_raw_call_cache_off_when_system_empty(monkeypatch):
    """cache_system=True + empty system → no system key at all (no wrapping of
    an empty string, no behavior change)."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "u", system="", cache_system=True)
    assert "system" not in captured[0], "empty system must not be wrapped or sent"


def test_raw_call_returns_cache_usage_fields(monkeypatch):
    """raw_call surfaces cache_creation/read token counts in the usage dict so
    track.log_usage can bill them (track.py already handles both fields)."""
    _patch_stream(monkeypatch)
    _text, usage = anthropic_client.raw_call("claude-opus-4-7", "u", system="SYS", cache_system=True)
    assert usage["cache_creation_input_tokens"] == 80
    assert "cache_read_input_tokens" in usage


# ---------- per-section retry caching (cache_user / user_suffix) ----------


def test_raw_call_cache_user_wraps_user_block(monkeypatch):
    """cache_user=True → user becomes a cache_control text block; the per-retry
    user_suffix is appended as a SEPARATE trailing UNCACHED block."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "BIG_STABLE_USER", cache_user=True, user_suffix="FEEDBACK")
    content = captured[0]["messages"][0]["content"]
    assert isinstance(content, list) and len(content) == 2, (
        f"expected [cached user, uncached feedback]; got {content!r}"
    )
    assert content[0]["text"] == "BIG_STABLE_USER"
    assert content[0]["cache_control"]["type"] == "ephemeral"
    assert content[1]["text"] == "FEEDBACK"
    assert "cache_control" not in content[1], "feedback suffix must stay uncached"


def test_raw_call_cache_user_no_suffix_single_block(monkeypatch):
    """cache_user=True with empty suffix → one cached user block (first attempt,
    no feedback yet)."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "U", cache_user=True)
    content = captured[0]["messages"][0]["content"]
    assert isinstance(content, list) and len(content) == 1
    assert content[0]["cache_control"]["type"] == "ephemeral"


def test_raw_call_suffix_concatenated_when_cache_off(monkeypatch):
    """cache_user=False but user_suffix given → concatenated string (identical
    content to the old behavior; no cache block)."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "U", cache_user=False, user_suffix="SUF")
    assert captured[0]["messages"][0]["content"] == "USUF"


def test_raw_call_default_plain_string_content(monkeypatch):
    """Defaults (no cache_user, no suffix) → plain string content, unchanged."""
    captured = _patch_stream(monkeypatch)
    anthropic_client.raw_call("claude-opus-4-7", "U")
    assert captured[0]["messages"][0]["content"] == "U"


def test_llm_call_writer_auto_enables_cache_user_and_forwards_suffix(monkeypatch):
    """role=='writer' auto-enables cache_user and forwards user_suffix to the
    anthropic client."""
    from deep_research import config, llm

    captured = {}

    def fake_raw_call(model, user, **kw):
        captured["user"] = user
        captured["cache_user"] = kw.get("cache_user")
        captured["user_suffix"] = kw.get("user_suffix")
        return "text", {}

    monkeypatch.setattr(llm.anthropic_client, "raw_call", fake_raw_call)
    monkeypatch.setattr(config, "model_for", lambda role: "claude-opus-4-7")
    llm.call("writer", "BODY", system="SYS", user_suffix="FB")
    assert captured["cache_user"] is True
    assert captured["user"] == "BODY"
    assert captured["user_suffix"] == "FB"


def test_llm_call_non_writer_concatenates_suffix(monkeypatch):
    """A non-writer role on a non-anthropic provider gets the suffix
    concatenated (identical content), since only the anthropic client splits."""
    from deep_research import config, llm

    captured = {}

    def fake_openai(model, user, **kw):
        captured["user"] = user
        return "text", {}

    monkeypatch.setattr(llm.openai_client, "raw_call", fake_openai)
    monkeypatch.setattr(config, "model_for", lambda role: "gpt-5.5")
    llm.call("grounding", "BODY", user_suffix="FB")
    assert captured["user"] == "BODYFB"


# ---------- llm.call dispatch policy ----------


def _patch_raw_call(monkeypatch):
    """Capture the cache_system value llm.call forwards into the anthropic
    client, and force the anthropic provider path via a claude model."""
    from deep_research import config, llm

    captured = {}

    def fake_raw_call(model, user, **kw):
        captured["cache_system"] = kw.get("cache_system")
        captured["cache_ttl"] = kw.get("cache_ttl")
        return "text", {}

    monkeypatch.setattr(llm.anthropic_client, "raw_call", fake_raw_call)
    # Pin both roles to a claude model so _provider() routes to anthropic.
    monkeypatch.setattr(config, "model_for", lambda role: "claude-opus-4-7")
    return captured


def test_llm_call_writer_role_enables_cache(monkeypatch):
    """role=='writer' auto-enables caching (cache_system defaults to None →
    derived True for writer)."""
    from deep_research import llm

    captured = _patch_raw_call(monkeypatch)
    llm.call("writer", "u", system="SYS")
    assert captured["cache_system"] is True


def test_llm_call_default_cache_ttl_is_5m(monkeypatch):
    """cache_ttl defaults to '5m' and is forwarded to raw_call."""
    from deep_research import llm

    captured = _patch_raw_call(monkeypatch)
    llm.call("writer", "u", system="SYS")
    assert captured["cache_ttl"] == "5m"


def test_llm_call_forwards_explicit_cache_ttl(monkeypatch):
    """A caller can reach the 1h extended cache via llm.call (Greptile PR #50
    — the knob was previously locked to 5m on the standard dispatch path)."""
    from deep_research import llm

    captured = _patch_raw_call(monkeypatch)
    llm.call("writer", "u", system="SYS", cache_ttl="1h")
    assert captured["cache_ttl"] == "1h"


def test_llm_call_non_writer_role_disables_cache(monkeypatch):
    """Non-writer roles (architect, etc.) do NOT auto-enable caching — their
    system prompts are smaller and per-call-unique."""
    from deep_research import llm

    captured = _patch_raw_call(monkeypatch)
    llm.call("architect", "u", system="SYS")
    assert captured["cache_system"] is False


def test_llm_call_explicit_override_wins(monkeypatch):
    """An explicit cache_system=True overrides the role-based default even for
    a non-writer role."""
    from deep_research import llm

    captured = _patch_raw_call(monkeypatch)
    llm.call("architect", "u", system="SYS", cache_system=True)
    assert captured["cache_system"] is True


def test_call_json_forwards_cache_params(monkeypatch):
    """call_json mirrors call()'s cache_system/cache_ttl so the JSON dispatch
    surface has the same explicit prompt-cache control (Greptile PR #50 r3 —
    previously these were droppable only via call() directly)."""
    from deep_research import llm

    captured = {}

    def fake_call(role, user, **kw):
        captured["cache_system"] = kw.get("cache_system")
        captured["cache_ttl"] = kw.get("cache_ttl")
        return '{"ok": true}'

    monkeypatch.setattr(llm, "call", fake_call)
    llm.call_json("architect", "u", cache_system=True, cache_ttl="1h")
    assert captured["cache_system"] is True
    assert captured["cache_ttl"] == "1h"


def test_call_json_default_cache_params_preserve_auto_enable(monkeypatch):
    """call_json defaults (cache_system=None, ttl 5m) keep the role-based
    auto-enable intact in call()."""
    from deep_research import llm

    captured = {}

    def fake_call(role, user, **kw):
        captured["cache_system"] = kw.get("cache_system")
        captured["cache_ttl"] = kw.get("cache_ttl")
        return '{"ok": true}'

    monkeypatch.setattr(llm, "call", fake_call)
    llm.call_json("writer", "u")
    assert captured["cache_system"] is None  # → call() derives True for writer
    assert captured["cache_ttl"] == "5m"
