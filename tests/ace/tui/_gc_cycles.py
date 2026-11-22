"""Shared ``gc.DEBUG_SAVEALL`` helpers for payload-cycle regressions.

A reference cycle is invisible to refcounting: the objects stay alive until the
cyclic collector runs, so a producer that creates one cycle per refresh pins its
payload (rows, snapshots, closures) until the next generation sweep. This module
counts that garbage deterministically instead of inferring it from RSS or timing.
It follows ``plan:202611/tui_cycle_churn.md``: warm up outside the measurement,
collect before sampling, run a bounded number of calls under
``gc.DEBUG_SAVEALL`` and count what the collector found unreachable.

Two entry points share that protocol:

* :func:`collect_cyclic_garbage` returns a :class:`~collections.Counter` of
  garbage by qualified type and drives awaitable results to completion on a
  fresh loop per call (the Textual, countdown-tick and native-failure guards).
* :func:`measure_cycle_garbage` / :func:`measure_cycle_garbage_async` return a
  :class:`CycleGarbage` report that also counts closure scaffolding by function
  ``__qualname__`` (the row-retention traversal guards).

The collector never runs with ``gc`` disabled and the sample never keeps probe
objects alive: :class:`CycleGarbage` holds counts only. Debug flags,
``gc.garbage`` and any survivors are restored/released in ``finally``, including
when the exercised path raises. Keep the *owners* of long-lived state (an app, a
cache, a roster) alive in the caller while sampling so their own teardown cycles
are not mistaken for per-call garbage, and keep fake timer lists, mock call
history and test closures out of the producer so they cannot become the
retainer.

Typical use::

    garbage = measure_cycle_garbage(lambda: concrete_agent_session_turn_rows(root))
    assert garbage.count(AGENT_TYPE) == 0
    assert garbage.function_count("visit") == 0
"""

from __future__ import annotations

import asyncio
import gc
import inspect
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import FunctionType
from typing import Final

__all__ = [
    "AGENT_TYPE",
    "CycleGarbage",
    "collect_cyclic_garbage",
    "measure_cycle_garbage",
    "measure_cycle_garbage_async",
    "qualified_type_name",
]

#: Qualified name of the presentation row every row-retention test counts.
AGENT_TYPE: Final = "sase.ace.tui.models.agent.Agent"

_DEFAULT_REPEAT: Final = 3
_DEFAULT_WARMUP: Final = 1
_COLLECT_ROUNDS: Final = 3


def qualified_type_name(obj: object) -> str:
    """Return ``module.qualname`` for ``type(obj)``."""
    kind = type(obj)
    return f"{kind.__module__}.{kind.__qualname__}"


@dataclass(frozen=True)
class CycleGarbage:
    """Counts of what one bounded SAVEALL sample found unreachable.

    Holds no references to the garbage itself, so reading or asserting on a
    report never keeps a payload alive.
    """

    repeat: int
    total: int
    shallow_bytes: int
    by_type: Mapping[str, int] = field(default_factory=dict)
    by_function: Mapping[str, int] = field(default_factory=dict)

    def count(self, type_name: str) -> int:
        """Return how many objects of exactly the qualified type were garbage."""
        return self.by_type.get(type_name, 0)

    def count_matching(self, needle: str) -> int:
        """Return garbage objects whose qualified type name contains ``needle``."""
        return sum(n for name, n in self.by_type.items() if needle in name)

    def function_count(self, qualname_part: str) -> int:
        """Return garbage functions whose ``__qualname__`` contains the text."""
        return sum(n for name, n in self.by_function.items() if qualname_part in name)

    def describe(self) -> str:
        """Render the sample for assertion messages and bead evidence."""
        types = ", ".join(
            f"{name}={count}"
            for name, count in sorted(
                self.by_type.items(), key=lambda item: (-item[1], item[0])
            )[:12]
        )
        functions = ", ".join(
            f"{name}={count}" for name, count in sorted(self.by_function.items())
        )
        return (
            f"{self.total} objects, {self.shallow_bytes} B in {self.repeat} calls; "
            f"types[{types}]; functions[{functions}]"
        )


def _settle() -> None:
    """Collect until a pass frees nothing more, outside any SAVEALL window."""
    for _ in range(_COLLECT_ROUNDS):
        if gc.collect() == 0:
            break


def _tally(repeat: int) -> CycleGarbage:
    """Collect once under the caller's debug flags and count ``gc.garbage``."""
    gc.collect()
    by_type: Counter[str] = Counter()
    by_function: Counter[str] = Counter()
    shallow_bytes = 0
    for obj in gc.garbage:
        by_type[qualified_type_name(obj)] += 1
        shallow_bytes += sys.getsizeof(obj, 0)
        if isinstance(obj, FunctionType):
            by_function[obj.__qualname__] += 1
    return CycleGarbage(
        repeat=repeat,
        total=len(gc.garbage),
        shallow_bytes=shallow_bytes,
        by_type=dict(by_type),
        by_function=dict(by_function),
    )


def _release(previous_flags: int) -> None:
    gc.set_debug(previous_flags)
    gc.garbage.clear()
    _settle()


def measure_cycle_garbage(
    produce: Callable[[], object],
    *,
    repeat: int = _DEFAULT_REPEAT,
    warmup: int = _DEFAULT_WARMUP,
) -> CycleGarbage:
    """Run ``produce`` ``repeat`` times under SAVEALL and count cyclic garbage.

    ``produce`` is called ``warmup`` times first (lazy imports, caches and
    interned state settle there) and its return value is dropped after every
    call. It must not be a coroutine function: use
    :func:`measure_cycle_garbage_async` for async producers.
    """
    if inspect.iscoroutinefunction(produce):
        raise TypeError("use measure_cycle_garbage_async for coroutine producers")
    previous_flags = gc.get_debug()
    try:
        for _ in range(warmup):
            produce()
        _settle()
        gc.garbage.clear()
        gc.set_debug(previous_flags | gc.DEBUG_SAVEALL)
        for _ in range(repeat):
            produce()
        return _tally(repeat)
    finally:
        _release(previous_flags)


async def measure_cycle_garbage_async(
    produce: Callable[[], Awaitable[object]],
    *,
    repeat: int = _DEFAULT_REPEAT,
    warmup: int = _DEFAULT_WARMUP,
) -> CycleGarbage:
    """Await ``produce`` ``repeat`` times under SAVEALL and count cyclic garbage.

    Collection runs on the calling (event-loop) thread, never on a worker
    thread. Drain or cancel the workers and timers the producer started before
    returning from it, so only genuinely obsolete payloads are sampled.
    """
    previous_flags = gc.get_debug()
    try:
        for _ in range(warmup):
            await produce()
        _settle()
        gc.garbage.clear()
        gc.set_debug(previous_flags | gc.DEBUG_SAVEALL)
        for _ in range(repeat):
            await produce()
        return _tally(repeat)
    finally:
        _release(previous_flags)


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
