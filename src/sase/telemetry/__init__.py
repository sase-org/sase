"""Prometheus telemetry for sase.

Public API:
- ``init_telemetry()`` — call once at process startup
- ``push_metrics()`` — push metrics to a Prometheus Push Gateway
- ``register_push_on_exit()`` — register atexit handler for push
- ``metrics`` — module containing all metric singletons
"""

from sase.telemetry._registry import (
    init_telemetry,
    push_metrics,
    register_push_on_exit,
)

__all__ = [
    "init_telemetry",
    "push_metrics",
    "register_push_on_exit",
]
