"""Stack and runtime metadata capture for TUI stall records."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import traceback
from typing import Any

from ._stall_watchdog_config import (
    MAX_WORKER_THREAD_STACK_DEPTH,
    MAX_WORKER_THREAD_STACKS,
)

log = logging.getLogger(f"{__package__}.stall_watchdog")


def format_thread_stack(thread_ident: int) -> list[str]:
    frame = sys._current_frames().get(thread_ident)
    if frame is None:
        return []
    return traceback.format_stack(frame)


def format_worker_thread_stacks(
    *,
    excluded_idents: set[int],
    max_threads: int = MAX_WORKER_THREAD_STACKS,
    max_depth: int = MAX_WORKER_THREAD_STACK_DEPTH,
) -> list[dict[str, Any]]:
    """Return bounded stacks for live threads other than loop/watchdog."""
    stacks: list[dict[str, Any]] = []
    try:
        frames = sys._current_frames()
        threads_by_ident = {
            thread.ident: thread
            for thread in threading.enumerate()
            if thread.ident is not None
        }

        def _thread_sort_key(ident: int) -> tuple[str, int]:
            thread = threads_by_ident.get(ident)
            return (thread.name if thread is not None else "", ident)

        worker_idents = sorted(
            (ident for ident in frames if ident not in excluded_idents),
            key=_thread_sort_key,
        )[:max_threads]
    except Exception:
        log.debug("Failed to enumerate worker threads for pump stall", exc_info=True)
        return stacks

    for ident in worker_idents:
        try:
            thread = threads_by_ident.get(ident)
            stacks.append(
                {
                    "name": thread.name if thread is not None else "unknown",
                    "ident": ident,
                    "daemon": thread.daemon if thread is not None else None,
                    "stack": traceback.format_stack(
                        frames[ident],
                        limit=max_depth,
                    ),
                }
            )
        except Exception:
            log.debug("Failed to format worker thread stack", exc_info=True)
    return stacks


def format_asyncio_task_stacks(
    loop: asyncio.AbstractEventLoop,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    try:
        live_tasks = sorted(asyncio.all_tasks(loop), key=lambda task: task.get_name())
    except Exception:
        log.debug("Failed to enumerate asyncio tasks for pump stall", exc_info=True)
        return tasks
    for task in live_tasks:
        try:
            await_chain = format_coroutine_await_chain(task.get_coro())
            stack = [
                line
                for frame in task.get_stack(limit=64)
                for line in traceback.format_stack(frame)
            ]
            stack.extend(line for awaited in await_chain for line in awaited["stack"])
            tasks.append(
                {
                    "name": task.get_name(),
                    "coroutine": repr(task.get_coro()),
                    "done": task.done(),
                    "stack": stack,
                    "await_chain": await_chain,
                }
            )
        except Exception:
            log.debug("Failed to format asyncio task stack", exc_info=True)
    return tasks


def format_coroutine_await_chain(coro: Any) -> list[dict[str, Any]]:
    """Walk nested ``await`` objects so records include the actual handler."""
    chain: list[dict[str, Any]] = []
    current: Any = coro
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frame = getattr(current, "cr_frame", None)
        if frame is None:
            frame = getattr(current, "gi_frame", None)
        if frame is None:
            frame = getattr(current, "ag_frame", None)
        chain.append(
            {
                "coroutine": repr(current),
                "stack": traceback.format_stack(frame) if frame is not None else [],
            }
        )
        current = getattr(current, "cr_await", None) or getattr(
            current, "gi_yieldfrom", None
        )
    return chain


def sase_version() -> str | None:
    try:
        from sase import __version__

        return __version__
    except Exception:
        return None
