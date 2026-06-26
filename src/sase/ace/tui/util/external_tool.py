"""Watchdog-aware terminal handoff helper for SASE-owned external tools.

Editor and artifact-viewer actions intentionally hand the terminal to a child
process via Textual ``App.suspend()``. While suspended the Textual event loop
is parked, which the always-on stall watchdog would otherwise record as a
generic event-loop freeze (see ``util/stall_watchdog.py``).

This helper records the handoff as ``external_tool_wait`` telemetry instead,
and keeps the watchdog from flagging the deliberate pause. When the global
suspend-signal hookup wired in ``actions/startup.py`` is active it already
pauses the watchdog for *every* ``suspend()``; this helper only pauses the
watchdog itself as a fallback when that hookup is unavailable, so the
reported editor/viewer paths stay protected regardless.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sase.logs import log_tui_external_tool_wait

log = logging.getLogger(__name__)


@contextmanager
def suspend_for_external_tool(
    app: Any,
    *,
    action: str,
    tool_kind: str,
    command: str | None = None,
    path_count: int | None = None,
    status_message: str | None = None,
) -> Iterator[None]:
    """Suspend Textual for a terminal handoff, recording it as a wait.

    Wraps ``app.suspend()`` and, on exit, appends one ``external_tool_wait``
    telemetry record with the rounded elapsed wall time plus low-cardinality
    metadata (action, tool kind, command basename, path/artifact count, current
    tab and index). When the global suspend-signal hookup is not wired the
    watchdog is paused around the suspend block as a fallback so the parked
    loop is never reported as a generic stall.

    The watchdog is resumed and the record is written on both the success and
    exception paths.
    """
    watchdog: Any = getattr(app, "_stall_watchdog", None)
    signals_wired = bool(getattr(app, "_stall_watchdog_suspend_signals_wired", False))
    manual_pause = watchdog is not None and not signals_wired

    start_mono = time.monotonic()
    if manual_pause:
        _safe_call(watchdog.pause, "stall watchdog pause failed")
    try:
        with app.suspend():
            if status_message:
                _write_terminal_status(status_message)
            yield
    finally:
        if manual_pause:
            _safe_call(watchdog.resume, "stall watchdog resume failed")
        _record_external_tool_wait(
            app,
            action=action,
            tool_kind=tool_kind,
            command=command,
            path_count=path_count,
            elapsed_seconds=time.monotonic() - start_mono,
        )


def _safe_call(fn: Any, message: str) -> None:
    try:
        fn()
    except Exception:
        log.debug(message, exc_info=True)


def _write_terminal_status(message: str) -> None:
    """Best-effort terminal-safe status line for an intentional handoff.

    Written to stdout inside the suspended block, where Textual has restored
    the real terminal, so an accidental keypress is visible for viewers that
    do not immediately clear the screen. Editors that take the alternate
    screen overwrite it; that is acceptable per the design's best-effort
    contract — it never blocks or forces a paint.
    """
    try:
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
    except Exception:
        log.debug("pre-handoff terminal status write failed", exc_info=True)


def _record_external_tool_wait(
    app: Any,
    *,
    action: str,
    tool_kind: str,
    command: str | None,
    path_count: int | None,
    elapsed_seconds: float,
) -> None:
    """Append one ``external_tool_wait`` record; never raise into the TUI."""
    try:
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": "external_tool_wait",
            "pid": os.getpid(),
            "action": action,
            "tool_kind": tool_kind,
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
        if command:
            record["command"] = os.path.basename(command)
        if path_count is not None:
            record["path_count"] = path_count
        current_tab = getattr(app, "current_tab", None)
        if current_tab is not None:
            record["current_tab"] = current_tab
        current_idx = getattr(app, "current_idx", None)
        if current_idx is not None:
            record["current_idx"] = current_idx
        version = _sase_version()
        if version is not None:
            record["sase_version"] = version
        log_tui_external_tool_wait(record)
    except Exception:
        log.debug("external-tool wait telemetry failed", exc_info=True)


def _sase_version() -> str | None:
    try:
        from sase import __version__

        return __version__
    except Exception:
        return None
