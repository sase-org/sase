"""Public interface for the always-on TUI stall watchdog."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ._stall_watchdog_capture import (
    format_asyncio_task_stacks as _format_asyncio_task_stacks,
    format_coroutine_await_chain as _format_coroutine_await_chain,
    format_thread_stack as _format_thread_stack,
    format_worker_thread_stacks as _format_worker_thread_stacks,
    sase_version as _sase_version,
)
from ._stall_watchdog_config import (
    DEFAULT_HITCH_RATE_LIMIT_PER_MINUTE as DEFAULT_HITCH_RATE_LIMIT_PER_MINUTE,
    DEFAULT_HITCH_THRESHOLD_SECONDS as DEFAULT_HITCH_THRESHOLD_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS as DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_THRESHOLD_SECONDS as DEFAULT_THRESHOLD_SECONDS,
    ENV_DISABLE as ENV_DISABLE,
    ENV_HITCH_DISABLE as ENV_HITCH_DISABLE,
    ENV_HITCH_THRESHOLD_SECONDS as ENV_HITCH_THRESHOLD_SECONDS,
    ENV_POLL_INTERVAL as ENV_POLL_INTERVAL,
    ENV_PUMP_DISABLE as ENV_PUMP_DISABLE,
    ENV_PUMP_HITCH_DISABLE as ENV_PUMP_HITCH_DISABLE,
    ENV_PUMP_HITCH_THRESHOLD_SECONDS as ENV_PUMP_HITCH_THRESHOLD_SECONDS,
    ENV_PUMP_POLL_INTERVAL as ENV_PUMP_POLL_INTERVAL,
    ENV_PUMP_THRESHOLD as ENV_PUMP_THRESHOLD,
    ENV_PUMP_THRESHOLD_SECONDS as ENV_PUMP_THRESHOLD_SECONDS,
    ENV_THRESHOLD as ENV_THRESHOLD,
    ENV_THRESHOLD_SECONDS as ENV_THRESHOLD_SECONDS,
    HITCH_RATE_LIMIT_WINDOW_SECONDS as HITCH_RATE_LIMIT_WINDOW_SECONDS,
    MAX_ASYNCIO_TASK_STACK_DEPTH as MAX_ASYNCIO_TASK_STACK_DEPTH,
    MAX_ASYNCIO_TASK_STACKS as MAX_ASYNCIO_TASK_STACKS,
    MAX_WORKER_THREAD_STACK_DEPTH as MAX_WORKER_THREAD_STACK_DEPTH,
    MAX_WORKER_THREAD_STACKS as MAX_WORKER_THREAD_STACKS,
    ContextProvider as ContextProvider,
    float_env as _float_env,
    HitchRateLimiter as _HitchRateLimiter,
    _TRUTHY as _TRUTHY,
)
from ._stall_watchdog_monitor import EventLoopStallWatchdog as _EventLoopStallWatchdog

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    """Return whether the always-on stall watchdog should run."""
    return os.environ.get(ENV_DISABLE, "").lower() not in _TRUTHY


def start_event_loop_stall_watchdog(
    loop: asyncio.AbstractEventLoop,
    *,
    app: Any | None = None,
    context_provider: ContextProvider | None = None,
) -> _EventLoopStallWatchdog | None:
    """Start the watchdog unless disabled by environment."""
    if not is_enabled():
        return None
    watchdog = _EventLoopStallWatchdog(
        loop,
        pump_app=app,
        context_provider=context_provider,
    )
    watchdog.start()
    return watchdog


def subscribe_watchdog_to_suspend_signals(
    app: Any,
    watchdog: _EventLoopStallWatchdog | None,
) -> bool:
    """Pause the watchdog across Textual ``suspend()`` terminal handoffs.

    The installed Textual runtime publishes ``app_suspend_signal`` before it
    parks the loop and ``app_resume_signal`` after it restarts. Subscribing
    with ``immediate=True`` runs the pause/resume callback synchronously during
    publish; the default posts it back to the app, which is too late because
    ``suspend()`` blocks the loop immediately after publishing.

    This is the global safety net for every ``app.suspend()`` call site, not
    just the helper-migrated ones. It is fully guarded so Textual versions
    without these exact instance signals keep working — in that case the
    external-tool helper falls back to pausing the watchdog around its own
    suspend block. Returns whether both signals were wired.

    The resume hook is subscribed first so a mid-wiring failure can never leave
    a pause subscription without its matching resume (an unbalanced resume on a
    depth-zero watchdog is a harmless no-op).
    """
    if watchdog is None:
        return False
    suspend_signal = getattr(app, "app_suspend_signal", None)
    resume_signal = getattr(app, "app_resume_signal", None)
    subscribe_suspend = getattr(suspend_signal, "subscribe", None)
    subscribe_resume = getattr(resume_signal, "subscribe", None)
    if not callable(subscribe_suspend) or not callable(subscribe_resume):
        return False
    try:
        subscribe_resume(app, lambda _data: watchdog.resume(), immediate=True)
        subscribe_suspend(app, lambda _data: watchdog.pause(), immediate=True)
    except Exception:
        log.debug("stall watchdog suspend-signal wiring skipped", exc_info=True)
        return False
    return True
