"""B4 (audit): explicit, extensible provider routing in llm._provider.

Routing is by an ordered prefix table + the OpenRouter org/model slug, with a
clear error for an unrecognized id (rather than a bare ValueError). These pin
the routing contract so a new model id fails loud with guidance instead of
silently misrouting.
"""

import pytest

from deep_research import llm


def test_openai_chat_prefix():
    assert llm._provider("gpt-5.5") == "openai"


def test_openai_embedding_prefix_no_longer_falls_through():
    # text-embedding-* now routes explicitly instead of raising.
    assert llm._provider("text-embedding-3-small") == "openai"


def test_openai_o_series_prefixes():
    # o1/o3/o4 families don't start with gpt- and have no slug — must route to
    # openai, not hit the ValueError.
    assert llm._provider("o1") == "openai"
    assert llm._provider("o3-mini") == "openai"
    assert llm._provider("o4-mini") == "openai"


def test_anthropic_prefix():
    assert llm._provider("claude-opus-4-7") == "anthropic"


def test_openrouter_slug():
    assert llm._provider("nvidia/nemotron-3-super-120b-a12b") == "openrouter"
    assert llm._provider("qwen/qwen3-235b-a22b") == "openrouter"


def test_unknown_id_raises_with_guidance():
    # A bare id with no known prefix and no slug fails loud, naming the table.
    with pytest.raises(ValueError, match="cannot infer provider"):
        llm._provider("gemini-2-pro")
