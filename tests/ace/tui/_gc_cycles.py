"""Shared controlled SAVEALL probe for payload-cycle regressions.

Follows ``plan:202611/tui_cycle_churn.md``: warm up outside the measurement,
collect before sampling, run a bounded number of calls under
``gc.DEBUG_SAVEALL``, and return qualified-type counts. Always restores the
previous debug flags and releases probe references and ``gc.garbage`` in
``finally``, including when the exercised path raises.
"""

from __future__ import annotations

import asyncio
import gc
import inspect
from collections import Counter
from collections.abc import Callable


def collect_cyclic_garbage(
    fn: Callable[[], object],
    *,
    repeat: int = 3,
    warmup: int = 1,
) -> Counter[str]:
    """Run *fn* under SAVEALL and return garbage counts by qualified type.

    Warms up outside the measurement, collects before sampling, and drops
    each return value before the next call so fixture return values never
    become the retainer. Never disables GC. Supports async producers by
    driving coroutine results to completion on a fresh loop per call without
    collecting on a worker thread.
    """
    for _ in range(warmup):
        result = fn()
        if inspect.isawaitable(result):
            asyncio.run(_await_result(result))  # type: ignore[arg-type]
        del result
    gc.collect()
    prev_debug = gc.get_debug()
    gc.set_debug(gc.DEBUG_SAVEALL)
    try:
        for _ in range(repeat):
            result = fn()
            if inspect.isawaitable(result):
                asyncio.run(_await_result(result))  # type: ignore[arg-type]
            del result
        gc.collect()
        return Counter(
            f"{type(obj).__module__}.{type(obj).__name__}" for obj in gc.garbage
        )
    finally:
        gc.set_debug(prev_debug)
        # Release inspection locals before clearing so the helper itself
        # never pins the measured cycle.
        gc.garbage.clear()


async def _await_result(awaitable: object) -> None:
    await awaitable  # type: ignore[misc]


__all__ = ["collect_cyclic_garbage"]
