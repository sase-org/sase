"""Local telemetry for sase.

Public API:
- ``init_telemetry()`` — call once at process startup
- ``flush_metrics()`` — persist pending deltas to the local core store
- ``register_flush_on_exit()`` — register an atexit flush
- ``metrics`` — module containing all metric singletons
"""

from sase.telemetry._registry import (
    cleanup_stale_groups,
    flush_metrics,
    init_telemetry,
    register_flush_on_exit,
)

__all__ = [
    "cleanup_stale_groups",
    "flush_metrics",
    "init_telemetry",
    "register_flush_on_exit",
]
