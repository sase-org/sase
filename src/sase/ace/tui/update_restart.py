"""Shared ACE restart helpers used by pane and app-level update flows."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_RESTART_WAIT_SECONDS = 60.0
NotifyFn = Callable[..., None]


_DEFAULT_RESTART_PURPOSE = "load new code"


def restart_after_update(
    app: Any,
    message: str,
    *,
    notify: NotifyFn | None = None,
    restart_purpose: str = _DEFAULT_RESTART_PURPOSE,
    track_pending: bool = True,
) -> None:
    """Notify briefly, then reuse the TUI + service-host restart machinery."""
    restart_after_update_when_ready(
        app,
        message,
        deferred=False,
        notify=notify,
        restart_purpose=restart_purpose,
        track_pending=track_pending,
    )


def restart_after_update_when_ready(
    app: Any,
    message: str,
    *,
    deferred: bool,
    deadline: float | None = None,
    notify: NotifyFn | None = None,
    restart_purpose: str = _DEFAULT_RESTART_PURPOSE,
    track_pending: bool = True,
    queued_at: float | None = None,
    restart_by: float | None = None,
) -> None:
    """Restart after tracked background procs have finished."""
    if deadline is None:
        deadline = time.monotonic() + _RESTART_WAIT_SECONDS
    if track_pending and not deferred:
        existing = getattr(app, "_pending_restart_chain", None)
        if existing is not None:
            existing["message"] = message
            existing["restart_purpose"] = restart_purpose
            existing["notify"] = notify
            running_now = running_background_procs(app)
            count = len(running_now)
            noun = "proc" if count == 1 else "procs"
            verb = "finishes" if count == 1 else "finish"
            _emit_restart_notice(
                app,
                f"{message} - restart queued until {count} {noun} {verb}.",
                notify=notify,
            )
            _publish_pending_restart(
                app,
                running_now,
                queued_at=existing.get("queued_at"),
                restart_by=existing.get("restart_by"),
            )
            return
    if track_pending and deferred:
        chain = getattr(app, "_pending_restart_chain", None)
        if isinstance(chain, dict):
            message = chain.get("message", message)
            restart_purpose = chain.get("restart_purpose", restart_purpose)
            notify = chain.get("notify", notify)
            queued_at = chain.get("queued_at", queued_at)
            restart_by = chain.get("restart_by", restart_by)
            deadline = chain.get("deadline", deadline)
    running_procs = running_background_procs(app)
    if running_procs and time.monotonic() < deadline:
        if track_pending and queued_at is None:
            now_wall = time.time()
            now_mono = time.monotonic()
            queued_at = now_wall
            restart_by = now_wall + (deadline - now_mono)
        if not deferred:
            count = len(running_procs)
            noun = "proc" if count == 1 else "procs"
            verb = "finishes" if count == 1 else "finish"
            _emit_restart_notice(
                app,
                f"{message} - restart queued until {count} {noun} {verb}.",
                notify=notify,
            )
        if track_pending:
            if not deferred:
                try:
                    app._pending_restart_chain = {  # type: ignore[attr-defined]
                        "message": message,
                        "restart_purpose": restart_purpose,
                        "notify": notify,
                        "deadline": deadline,
                        "queued_at": queued_at,
                        "restart_by": restart_by,
                    }
                except Exception:
                    pass
            _publish_pending_restart(
                app,
                running_procs,
                queued_at=queued_at,
                restart_by=restart_by,
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
                    restart_purpose=restart_purpose,
                    track_pending=track_pending,
                    queued_at=queued_at,
                    restart_by=restart_by,
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
        f"{message} — restarting ACE to {restart_purpose}.",
        notify=notify,
    )
    if track_pending:
        try:
            app._pending_restart_chain = None  # type: ignore[attr-defined]
        except Exception:
            pass
    restart = getattr(app, "_restart_tui", None)
    if callable(restart):
        restart(restart_axe=True)
        return
    if track_pending:
        _clear_pending_restart(app)


def _publish_pending_restart(
    app: Any,
    running_procs: list[Any],
    *,
    queued_at: float | None,
    restart_by: float | None,
) -> None:
    """Publish a coalesced pending-restart record when the app supports it."""
    setter = getattr(app, "_set_pending_update_restart", None)
    if not callable(setter):
        return
    if queued_at is None or restart_by is None:
        return
    try:
        from sase.ace.tui.update_gear import PendingUpdateRestart

        setter(
            PendingUpdateRestart(
                blocker_labels=tuple(_proc_display_name(p) for p in running_procs),
                blocker_identities=tuple(
                    str(
                        getattr(p, "durable_proc_id", None) or getattr(p, "proc_id", "")
                    )
                    for p in running_procs
                ),
                queued_at=queued_at,
                restart_by=restart_by,
            )
        )
    except Exception:
        pass


def _clear_pending_restart(app: Any) -> None:
    """Clear the published pending record when the restart cannot run."""
    setter = getattr(app, "_set_pending_update_restart", None)
    if not callable(setter):
        return
    try:
        setter(None)
    except Exception:
        pass


def running_background_procs(app: Any) -> list[Any]:
    """Return observed active procs that must finish before ACE can restart.

    Excludes monitor turns because they are host-level follow-up supervisors,
    and service daemons because a daemon has no terminal state: waiting on one
    can only expire. Every other active proc (including transient oneshot
    ``!`` commands) is ordinary background work and should drain first.
    """
    from sase.ace.tui.proc_observer import (
        is_monitor_turn_row,
        is_service_daemon_row,
        proc_projection_for,
    )

    return [
        row
        for row in proc_projection_for(app).active_rows()
        if not is_monitor_turn_row(row) and not is_service_daemon_row(row)
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
