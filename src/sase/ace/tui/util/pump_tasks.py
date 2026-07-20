"""Helpers for running slow async work outside Textual's message pump.

Textual awaits async ``call_later`` and timer callbacks on the App's serial
message pump.  Any callback that awaits disk, subprocess, or worker-thread
work must therefore be spawned as a free-standing event-loop task instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Coroutine
from dataclasses import dataclass
from time import monotonic
from typing import Any

log = logging.getLogger(__name__)

_REGISTRY_NAMES_ATTR = "_pump_free_task_registry_attrs"
_FAILURE_SUMMARY_INTERVAL_SECONDS = 5 * 60
_MAX_TRACKED_FAILURE_SIGNATURES = 256


@dataclass
class _FailureLogState:
    last_reported_at: float
    suppressed_count: int = 0


_failure_log_states: OrderedDict[tuple[str, str, str], _FailureLogState] = OrderedDict()


def _log_task_failure(name: str, error: Exception) -> None:
    """Log one traceback per failure signature, then periodic summaries."""
    error_type = f"{type(error).__module__}.{type(error).__qualname__}"
    message = " ".join(str(error).split()) or "<no message>"
    signature = (name, error_type, message)
    now = monotonic()
    state = _failure_log_states.get(signature)
    if state is None:
        _failure_log_states[signature] = _FailureLogState(last_reported_at=now)
        if len(_failure_log_states) > _MAX_TRACKED_FAILURE_SIGNATURES:
            _failure_log_states.popitem(last=False)
        log.exception("pump-free task %s failed", name)
        return

    _failure_log_states.move_to_end(signature)
    state.suppressed_count += 1
    if now - state.last_reported_at < _FAILURE_SUMMARY_INTERVAL_SECONDS:
        return

    log.error(
        "pump-free task %s repeated failure %d time(s) since last report: %s: %s",
        name,
        state.suppressed_count,
        error_type,
        message,
    )
    state.last_reported_at = now
    state.suppressed_count = 0


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
        except Exception as error:
            _log_task_failure(name, error)

    task.add_done_callback(_done)
    return task


def cancel_pump_free_tasks(owner: object) -> None:
    """Cancel every still-running task registered through this helper."""
    registry_names = tuple(getattr(owner, _REGISTRY_NAMES_ATTR, ()))
    for registry_attr in registry_names:
        for task in tuple(getattr(owner, registry_attr, ())):
            task.cancel()
