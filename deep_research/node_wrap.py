"""Graph-node decorator (p1-checklist item 36).

Wraps each pipeline node's `run()` entrypoint so every node-level invocation
logs entry, exit, duration, and a cost-attribution row to cost_tracking with a
`node:<name>` model tag. Cost-by-node breakdowns are then trivially computable
from the existing ledger at every milestone.

Token spend inside the node is still logged by the per-client `_log_usage`
hooks (gpt55/Opus/OpenRouter); this wrapper adds the node-level boundary marker
so we can group ledger rows by node by querying `note LIKE 'node:%'` or by
filtering rows between the entry/exit markers.
"""
import functools
import time

from ._env import log_usage


def node(name: str):
    """`@node('role_play')` — instrument a `run(input)->output` callable."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            log_usage(f"node:{name}", {}, note=f"node:{name} enter")
            try:
                out = fn(*args, **kwargs)
                return out
            finally:
                dur = round(time.time() - t0, 2)
                log_usage(f"node:{name}", {},
                          note=f"node:{name} exit dur={dur}s")
        return wrapper
    return deco
