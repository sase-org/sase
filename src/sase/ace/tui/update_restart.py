"""Shared ACE restart helpers used by pane and app-level update flows."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_RESTART_WAIT_SECONDS = 60.0
NotifyFn = Callable[..., None]


def restart_after_update(
    app: Any,
    message: str,
    *,
    notify: NotifyFn | None = None,
) -> None:
    """Notify briefly, then reuse the TUI + axe restart machinery."""
    restart_after_update_when_ready(app, message, deferred=False, notify=notify)


def restart_after_update_when_ready(
    app: Any,
    message: str,
    *,
    deferred: bool,
    deadline: float | None = None,
    notify: NotifyFn | None = None,
) -> None:
    """Restart after tracked background procs have finished."""
    if deadline is None:
        deadline = time.monotonic() + _RESTART_WAIT_SECONDS
    running_procs = running_background_procs(app)
    if running_procs and time.monotonic() < deadline:
        if not deferred:
            count = len(running_procs)
            noun = "proc" if count == 1 else "procs"
            verb = "finishes" if count == 1 else "finish"
            _emit_restart_notice(
                app,
                f"{message} - restart queued until {count} {noun} {verb}.",
                notify=notify,
            )
        set_timer = getattr(app, "set_timer", None)
        if callable(set_timer):
            set_timer(
                1.0,
                lambda: restart_after_update_when_ready(
                    app,
                    message,
                    deferred=True,
                    deadline=deadline,
                    notify=notify,
                ),
            )
        return

    if running_procs:
        _emit_restart_notice(
            app,
            f"{message} - restart wait expired; restarting with "
            f"{_blocking_proc_summary(running_procs)} still active.",
            severity="warning",
            notify=notify,
        )

    _emit_restart_notice(
        app,
        f"{message} — restarting ACE to load new code.",
        notify=notify,
    )
    restart = getattr(app, "_restart_tui", None)
    if callable(restart):
        restart(restart_axe=True)


def running_background_procs(app: Any) -> list[Any]:
    """Return observed active procs that must finish before ACE can restart.

    Excludes monitor shells: a detached ``sase monitor start`` supervisor
    outlives ACE by design, so it must not block a self-update restart.
    """
    from sase.ace.tui.proc_observer import is_monitor_shell_row, proc_projection_for

    return [
        row
        for row in proc_projection_for(app).active_rows()
        if not is_monitor_shell_row(row)
    ]


def _emit_restart_notice(
    app: Any,
    message: str,
    *,
    severity: str = "information",
    notify: NotifyFn | None = None,
) -> None:
    emit = notify if callable(notify) else getattr(app, "notify", None)
    if callable(emit):
        emit(message, severity=severity)


def _blocking_proc_summary(procs: list[Any]) -> str:
    """Return a compact user-facing description of restart blockers."""
    count = len(procs)
    noun = "proc" if count == 1 else "procs"
    names = [_proc_display_name(proc) for proc in procs[:3]]
    suffix = "" if count <= 3 else f", and {count - 3} more"
    return f"{count} {noun}: {', '.join(names)}{suffix}"


def _proc_display_name(proc: Any) -> str:
    for attr in ("label", "display_name", "proc_type", "proc_id"):
        value = getattr(proc, attr, None)
        if isinstance(value, str) and value:
            return value
    return "unknown proc"


__all__ = [
    "restart_after_update",
    "restart_after_update_when_ready",
    "running_background_procs",
]
