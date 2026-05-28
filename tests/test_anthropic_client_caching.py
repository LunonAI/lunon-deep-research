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


# ---------- llm.call dispatch policy ----------


def _patch_raw_call(monkeypatch):
    """Capture the cache_system value llm.call forwards into the anthropic
    client, and force the anthropic provider path via a claude model."""
    from deep_research import config, llm

    captured = {}

    def fake_raw_call(model, user, **kw):
        captured["cache_system"] = kw.get("cache_system")
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
