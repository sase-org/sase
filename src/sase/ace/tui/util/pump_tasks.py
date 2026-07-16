"""Helpers for running slow async work outside Textual's message pump.

Textual awaits async ``call_later`` and timer callbacks on the App's serial
message pump.  Any callback that awaits disk, subprocess, or worker-thread
work must therefore be spawned as a free-standing event-loop task instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)

_REGISTRY_NAMES_ATTR = "_pump_free_task_registry_attrs"


def spawn_pump_free_task[T](
    owner: object,
    coro: Coroutine[Any, Any, T],
    *,
    name: str,
    registry_attr: str,
) -> asyncio.Task[T] | None:
    """Spawn and retain ``coro`` without involving Textual's message pump.

    The owner-held registry prevents the task from being garbage-collected,
    supports lifecycle cancellation, and is pruned by the done callback.  A
    missing running loop is tolerated for narrow unit-test/fallback callers;
    the coroutine is closed so it cannot emit an un-awaited warning.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        log.debug("pump-free task %s skipped without a running loop", name)
        return None

    task = loop.create_task(coro, name=name)
    registry = getattr(owner, registry_attr, None)
    if registry is None:
        registry = set()
        setattr(owner, registry_attr, registry)
    registry.add(task)

    registry_names = getattr(owner, _REGISTRY_NAMES_ATTR, None)
    if registry_names is None:
        registry_names = set()
        setattr(owner, _REGISTRY_NAMES_ATTR, registry_names)
    registry_names.add(registry_attr)

    def _done(completed: asyncio.Task[T]) -> None:
        registry.discard(completed)
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception:
            log.exception("pump-free task %s failed", name)

    task.add_done_callback(_done)
    return task


def cancel_pump_free_tasks(owner: object) -> None:
    """Cancel every still-running task registered through this helper."""
    registry_names = tuple(getattr(owner, _REGISTRY_NAMES_ATTR, ()))
    for registry_attr in registry_names:
        for task in tuple(getattr(owner, registry_attr, ())):
            task.cancel()
