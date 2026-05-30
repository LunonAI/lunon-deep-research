"""Unified role→model→provider dispatcher.

call(role, user, ...) resolves the model via config.model_for(role), infers the
provider from the model-id prefix, and routes to the matching client. Gate-
affecting callers pass `seed=` for best-effort determinism (plan point 12).
"""

import json
import re

from . import config
from .clients import anthropic_client, openai_client, openrouter_client

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# Anthropic only caches a prompt block that is at least 1024 tokens; below that
# a `cache_control` marker buys nothing (and adds the one-time cache-write
# surcharge). 4096 chars ≈ 1024 tokens at the ~4 chars/token of the English
# instruction prompts here (CJK packs more tokens per char, so this is a safe
# lower bound). Measured system blocks: architect ~16k chars / ~4k tok and the
# writer block ~27k chars clear it; scout/design_guide/grounding/inner_scorer
# are all ≤1.3k chars (~100-300 tok) and stay uncached by design.
_CACHE_SYSTEM_MIN_CHARS = 4096


def _should_cache_system(role: str, system) -> bool:
    """Auto-enable anthropic system-prompt caching when it actually pays off.

    True for the `writer` (its large per-task-stable block was the original
    cached call) and for any call whose system prompt clears the anthropic
    minimum cacheable size — which today captures the architect's ~4k-token
    static `_SYSTEM`, re-sent on every plan, on its shortfall-retry, and across
    every task (B1). Caching is output-invariant: the model sees identical
    tokens, so this never changes results, only cost.
    """
    if role == "writer":
        return True
    return isinstance(system, str) and len(system) >= _CACHE_SYSTEM_MIN_CHARS


def _provider(model: str) -> str:
    if model.startswith("gpt-"):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if "/" in model:
        return "openrouter"
    raise ValueError(f"cannot infer provider for model {model!r}")


def call(
    role,
    user,
    system="",
    *,
    max_tokens=8000,
    seed=None,
    effort="low",
    reasoning_effort=None,
    think=False,
    note="",
    timeout=300,
    max_retries=3,
    cache_system=None,
    cache_ttl="5m",
    cache_user=None,
    user_suffix="",
):
    """Return assistant text for `role`. Auto-routes by model provider.

    effort: unified reasoning level ('low'|'medium'|'high'). openai maps it to
    reasoning_effort; anthropic maps it to output_config.effort (only when
    think=True); openrouter ignores it. `reasoning_effort` kept as a back-compat
    alias for openai callers.

    cache_system: anthropic-only prompt-cache toggle. `None` (default) auto-
    enables caching via `_should_cache_system()`: the `writer` role plus any
    call whose system block clears the anthropic minimum cacheable size
    (~1024 tokens). That covers the writer's 27.5 KB block and the architect's
    ~4k-token static `_SYSTEM` (B1) — the two calls where the byte-identical,
    frequently re-sent prefix makes caching pay off; the smaller per-role
    prompts stay uncached. Caching is output-invariant (the model sees identical
    tokens), so this never affects quality. Pass an explicit bool to override.

    seed: forwarded on the openai/openrouter paths for best-effort determinism.
    The anthropic path RAISES if seed is not None — the Messages API has no seed
    parameter, so honoring the determinism contract there is impossible (B3).

    cache_ttl: anthropic cache lifetime — "5m" (GA default, refresh-on-use,
    covers the back-to-back writer calls within a task) or "1h" (extended,
    for callers that batch with longer idle gaps). Only used when caching
    is active on the anthropic path.
    cache_user / user_suffix: per-section retry caching (anthropic only). `None`
    auto-enables for the `writer` role. `user` becomes a cache block and
    `user_suffix` (per-retry feedback) is appended uncached after it, so a
    section's retries read the heavy stable prompt at 0.1×. Output-invariant.
    """
    model = config.model_for(role)
    if not model:
        raise RuntimeError(
            f"role {role!r} has no model configured (zh_writer may be intentionally dropped — caller must check)"
        )
    prov = _provider(model)
    tag = note or role
    eff = reasoning_effort or effort
    # Only the anthropic client supports the cached-user-block + uncached-suffix
    # split. For other providers (and uncached anthropic), concatenate so the
    # model sees identical content.
    full_user = f"{user}{user_suffix}" if user_suffix else user
    if prov == "openai":
        text, _ = openai_client.raw_call(
            model,
            full_user,
            system=system,
            reasoning_effort=eff,
            max_completion_tokens=max_tokens,
            seed=seed,
            note=tag,
            timeout=timeout,
            max_retries=max_retries,
        )
        return text
    if prov == "anthropic":
        # B3: the Anthropic Messages API has no `seed` parameter, so a seed here
        # cannot produce determinism. The openai/openrouter branches forward
        # `seed`; this branch used to drop it SILENTLY, so a caller adding a
        # seeded Opus call expecting reproducibility would get none and never
        # know. Fail loud instead — the contract is now honest. (No current
        # caller hits this: every seed= site routes to openai/openrouter.)
        if seed is not None:
            raise ValueError(
                f"seed={seed!r} passed for role {role!r}, which routes to the "
                f"anthropic model {model!r}; the Anthropic Messages API cannot "
                f"honor a determinism seed. Drop seed for this role, or route it "
                f"to a provider that supports seeding (openai/openrouter)."
            )
        # cache_system / cache_user are anthropic-only — resolve them here so the
        # openai/openrouter paths don't do the dead computation.
        cache = cache_system if cache_system is not None else _should_cache_system(role, system)
        cache_u = cache_user if cache_user is not None else (role == "writer")
        text, _ = anthropic_client.raw_call(
            model,
            user,
            system=system,
            max_tokens=max_tokens,
            think=think,
            effort=eff,
            note=tag,
            max_retries=max_retries,
            cache_system=cache,
            cache_ttl=cache_ttl,
            cache_user=cache_u,
            user_suffix=user_suffix,
        )
        return text
    text, _ = openrouter_client.raw_call(
        model,
        full_user,
        system=system,
        max_tokens=max_tokens,
        seed=seed,
        note=tag,
        timeout=min(timeout, 180),
        max_retries=max_retries,
    )
    return text


_THINK = re.compile(r"<think>.*?</think>|<reasoning>.*?</reasoning>", re.DOTALL | re.IGNORECASE)


def _balanced_scan(text, open_c, close_c):
    """Yield top-level balanced (open_c..close_c) substrings, last first."""
    spans, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == open_c:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_c and depth:
            depth -= 1
            if depth == 0 and start != -1:
                spans.append(text[start : i + 1])
    return list(reversed(spans))


def extract_json(text):
    """Robust JSON extraction for reasoning models (Nemotron/gpt-5.x): strips
    <think>/<reasoning> blocks, prefers a fenced block, else the LAST balanced
    JSON value (reasoning prose usually precedes the answer)."""
    text = _THINK.sub("", text or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        for cand in _balanced_scan(text, open_c, close_c):
            try:
                return json.loads(cand)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No JSON found in response: {text[:300]}")


def embed(role: str, texts: list[str], *, note: str = "", max_retries: int = 3, timeout: int = 120, batch: int = 100):
    """Return one embedding vector per input text. Order preserved.

    Routes by model id like `call()` does, but currently only OpenAI's
    embeddings endpoint is wired. To add another provider (Cohere/Voyage/etc.),
    extend `_provider()` (e.g. an `"emb/"` prefix convention) and add a
    matching client's `embed()` function — the dispatch shape mirrors `call()`.
    """
    model = config.model_for(role)
    if not model:
        raise RuntimeError(f"embedder role {role!r} has no model configured")
    # Only OpenAI embeddings are wired today. Identify by model id heuristic:
    # text-embedding-* is OpenAI's family. Other prefixes are not yet supported.
    if not model.startswith("text-embedding-"):
        raise NotImplementedError(
            f"embed() only supports OpenAI text-embedding-* models today (got {model!r}). "
            f"To add Cohere/Voyage/etc., extend deep_research/llm.py and a new client module."
        )
    return openai_client.embed(model, texts, max_retries=max_retries, timeout=timeout, note=note or role, batch=batch)


def call_json(
    role,
    user,
    system="",
    *,
    max_tokens=8000,
    seed=None,
    effort="medium",
    reasoning_effort=None,
    think=False,
    note="",
    retries=2,
    timeout=300,
    max_retries=3,
    cache_system=None,
    cache_ttl="5m",
    cache_user=None,
    user_suffix="",
):
    """call() + JSON extraction with a light retry on parse failure.

    cache_system / cache_ttl / cache_user / user_suffix mirror `call()` so
    callers using the JSON dispatch surface have the same explicit prompt-cache
    control. `None` keeps the role-based auto-enable in `call()`.
    """
    last = None
    for _ in range(retries + 1):
        txt = call(
            role,
            user,
            system=system,
            max_tokens=max_tokens,
            seed=seed,
            effort=effort,
            reasoning_effort=reasoning_effort,
            think=think,
            note=note,
            timeout=timeout,
            max_retries=max_retries,
            cache_system=cache_system,
            cache_ttl=cache_ttl,
            cache_user=cache_user,
            user_suffix=user_suffix,
        )
        try:
            return extract_json(txt)
        except ValueError as e:
            last = e
    raise RuntimeError(f"call_json({role}) failed to yield JSON: {last}")
