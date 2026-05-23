"""Engine-local read-only caches.

Subpackage for lazy-loaded reference data sourced from the harness or prior
W-runs. Each module here MUST fail-soft (return empty / falsey) if its
source file is missing — the engine still has to run on machines without
the full DRB results tree.
"""
