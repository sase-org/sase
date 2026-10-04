"""Shared ACE restart helpers used by pane and app-level update flows."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

_RESTART_WAIT_SECONDS = 60.0
NotifyFn = Callable[..., None]
RestartBlockerKind = Literal["session_worker", "submission", "install", "legacy_tui"]

_DEFAULT_RESTART_PURPOSE = "load new code"
_FALLBACK_SUBMISSION_LABEL = "durable submission"
_KIND_GROUP: dict[RestartBlockerKind, str] = {
    "session_worker": "tui",
    "legacy_tui": "tui",
    "submission": "submission",
    "install": "install",
}
_GROUP_NOUNS = {
    "tui": ("TUI task", "TUI tasks"),
    "submission": ("submission", "submissions"),
    "install": ("installation change", "installation changes"),
}
_GROUP_ORDER = ("tui", "submission", "install")


@dataclass(frozen=True, slots=True)
class RestartBlocker:
    """One piece of work that must finish before an update restart."""

    identity: str
    label: str
    kind: RestartBlockerKind = "session_worker"


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
    restart_token: object | None = None,
) -> None:
    """Restart after TUI-local work and installation mutations have finished."""
    if deadline is None:
        deadline = time.monotonic() + _RESTART_WAIT_SECONDS
    if deferred and not _restart_token_is_current(app, restart_token):
        return
    if track_pending and not deferred:
        existing = getattr(app, "_pending_restart_chain", None)
        if existing is not None:
            existing["message"] = message
            existing["restart_purpose"] = restart_purpose
            existing["notify"] = notify
            blockers_now = _current_blockers(app)
            if blockers_now:
                count_phrase, verb = _wait_count_phrase(blockers_now)
                _emit_restart_notice(
                    app,
                    f"{message} - restart queued until {count_phrase} {verb}.",
                    notify=notify,
                )
                _publish_pending_restart(
                    app,
                    blockers_now,
                    queued_at=existing.get("queued_at"),
                    restart_by=existing.get("restart_by"),
                )
                return
    if track_pending and deferred:
        chain = getattr(app, "_pending_restart_chain", None)
        if not isinstance(chain, dict):
            return
        message = chain.get("message", message)
        restart_purpose = chain.get("restart_purpose", restart_purpose)
        notify = chain.get("notify", notify)
        queued_at = chain.get("queued_at", queued_at)
        restart_by = chain.get("restart_by", restart_by)
        deadline = chain.get("deadline", deadline)
        restart_token = chain.get("token", restart_token)
    blockers = _current_blockers(app)
    if blockers and time.monotonic() < deadline:
        if track_pending and queued_at is None:
            now_wall = time.time()
            now_mono = time.monotonic()
            queued_at = now_wall
            restart_by = now_wall + (deadline - now_mono)
        if not deferred:
            count_phrase, verb = _wait_count_phrase(blockers)
            _emit_restart_notice(
                app,
                f"{message} - restart queued until {count_phrase} {verb}.",
                notify=notify,
            )
        token = restart_token or _begin_restart_wait(app)
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
                        "token": token,
                    }
                except Exception:
                    pass
            _publish_pending_restart(
                app,
                blockers,
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
                    restart_token=token,
                ),
            )
        return

    if blockers:
        _emit_restart_notice(
            app,
            f"{message} - restart wait expired; restarting with "
            f"{_blocking_summary(blockers)} still active.",
            severity="warning",
            notify=notify,
        )

    _emit_restart_notice(
        app,
        f"{message} — restarting ACE to {restart_purpose}.",
        notify=notify,
    )
    _clear_restart_wait(app, track_pending=track_pending)
    restart = getattr(app, "_restart_tui", None)
    if callable(restart):
        restart(restart_axe=True)
        return
    if track_pending:
        _clear_pending_restart(app)


def collect_restart_blockers(app: Any) -> tuple[RestartBlocker, ...]:
    """Return TUI-local and installation blockers for an update restart.

    Independent durable commands, tool runs, monitors, oneshots, and
    service daemons are not restart dependencies. Presence in the session
    overlay or submit-worker map is authoritative even after a worker
    thread has returned, so a queued completion callback still blocks.
    """
    seen: set[str] = set()
    blockers: list[RestartBlocker] = []

    def add(
        identity: str,
        label: str,
        kind: RestartBlockerKind,
        aliases: Iterable[str] = (),
    ) -> None:
        keys = [identity, *aliases]
        if any(key in seen for key in keys if key):
            return
        if not identity:
            return
        text = label.strip() or identity
        seen.update(key for key in keys if key)
        blockers.append(RestartBlocker(identity=identity, label=text, kind=kind))

    from sase.ace.tui.quit_impact import (
        durable_submit_workers,
        overlay_row_label,
        session_overlay_rows,
    )

    for row in session_overlay_rows(app):
        identity = _row_identity(row)
        if not identity:
            continue
        add(identity, overlay_row_label(row) or identity, "session_worker")

    for proc_id in getattr(app, "_session_workers", {}):
        identity = str(proc_id or "")
        if not identity:
            continue
        add(identity, "TUI task", "session_worker")

    cached_rows = _cached_projection_rows(app)
    for placeholder_id in durable_submit_workers(app):
        identity = str(placeholder_id or "")
        if not identity:
            continue
        row = _row_by_id(cached_rows, identity)
        label = (
            overlay_row_label(row) if row is not None else _FALLBACK_SUBMISSION_LABEL
        )
        aliases: list[str] = []
        if row is not None:
            durable_id = getattr(row, "durable_proc_id", None)
            if durable_id and str(durable_id) != identity:
                aliases.append(str(durable_id))
        add(identity, label, "submission", aliases)

    session_id = _current_session_id(app)
    try:
        from sase.ace.tui._proc_observer_models import (
            is_install_mutation_row,
            proc_status_is_active,
        )
    except Exception:
        return tuple(blockers)
    for row in cached_rows:
        try:
            if not proc_status_is_active(getattr(row, "status", "")):
                continue
            identity = _row_identity(row)
            if not identity:
                continue
            if is_install_mutation_row(row):
                add(identity, overlay_row_label(row) or identity, "install")
                continue
            if _is_local_legacy_tui(row, session_id):
                add(identity, overlay_row_label(row) or identity, "legacy_tui")
        except Exception:
            continue

    return tuple(blockers)


def running_background_procs(app: Any) -> list[RestartBlocker]:
    """Return restart blockers; name kept for existing imports."""
    return list(collect_restart_blockers(app))


def _current_blockers(app: Any) -> tuple[RestartBlocker, ...]:
    try:
        raw = running_background_procs(app)
    except Exception:
        return ()
    return _normalize_blockers(raw)


def _normalize_blockers(items: Iterable[Any]) -> tuple[RestartBlocker, ...]:
    blockers: list[RestartBlocker] = []
    for item in items or ():
        if isinstance(item, RestartBlocker):
            blockers.append(item)
            continue
        identity = _item_identity(item)
        if not identity:
            continue
        blockers.append(
            RestartBlocker(
                identity=identity,
                label=_item_label(item) or identity,
                kind=_as_blocker_kind(getattr(item, "kind", "session_worker")),
            )
        )
    return tuple(blockers)


def _publish_pending_restart(
    app: Any,
    blockers: tuple[RestartBlocker, ...],
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

        count_phrase, verb = _wait_count_phrase(blockers)
        setter(
            PendingUpdateRestart(
                blocker_labels=tuple(item.label for item in blockers),
                blocker_identities=tuple(item.identity for item in blockers),
                queued_at=queued_at,
                restart_by=restart_by,
                wait_phrase=f"{count_phrase} {verb}",
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


def _begin_restart_wait(app: Any) -> object:
    token = object()
    try:
        app._restart_wait_token = token  # type: ignore[attr-defined]
    except Exception:
        pass
    return token


def _restart_token_is_current(app: Any, token: object | None) -> bool:
    if token is None:
        return True
    current = getattr(app, "_restart_wait_token", None)
    return current is token


def _clear_restart_wait(app: Any, *, track_pending: bool) -> None:
    try:
        app._restart_wait_token = None  # type: ignore[attr-defined]
    except Exception:
        pass
    if track_pending:
        try:
            app._pending_restart_chain = None  # type: ignore[attr-defined]
        except Exception:
            pass


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


def _wait_count_phrase(blockers: tuple[RestartBlocker, ...]) -> tuple[str, str]:
    """Return ``(count phrase, verb)`` for queued/expired restart copy."""
    counts = dict.fromkeys(_GROUP_ORDER, 0)
    for blocker in blockers:
        group = _KIND_GROUP.get(blocker.kind, "tui")
        counts[group] = counts.get(group, 0) + 1
    parts: list[str] = []
    for group in _GROUP_ORDER:
        count = counts[group]
        if count <= 0:
            continue
        singular, plural = _GROUP_NOUNS[group]
        noun = singular if count == 1 else plural
        parts.append(f"{count} {noun}")
    if not parts:
        total = len(blockers)
        noun = "TUI task" if total == 1 else "TUI tasks"
        parts.append(f"{total} {noun}")
    total = len(blockers)
    verb = "finishes" if total == 1 else "finish"
    return _join_phrases(parts), verb


def _join_phrases(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _blocking_summary(blockers: tuple[RestartBlocker, ...]) -> str:
    """Return a compact user-facing description of restart blockers."""
    phrase, _verb = _wait_count_phrase(blockers)
    names = [item.label for item in blockers[:3]]
    suffix = "" if len(blockers) <= 3 else f", and {len(blockers) - 3} more"
    return f"{phrase}: {', '.join(names)}{suffix}"


def _cached_projection_rows(app: Any) -> tuple[Any, ...]:
    projection = getattr(app, "_proc_projection", None)
    rows = getattr(projection, "rows", None)
    if not rows:
        return ()
    return tuple(rows)


def _current_session_id(app: Any) -> str | None:
    projection = getattr(app, "_proc_projection", None)
    session_id = getattr(projection, "session_id", None)
    if session_id:
        return str(session_id)
    bound = getattr(app, "_proc_session_id", None)
    return str(bound) if bound else None


def _row_identity(row: Any) -> str:
    durable = getattr(row, "durable_proc_id", None)
    if durable:
        return str(durable)
    proc_id = getattr(row, "proc_id", None)
    return str(proc_id) if proc_id else ""


def _row_by_id(rows: tuple[Any, ...], identity: str) -> Any | None:
    for row in rows:
        proc_id = str(getattr(row, "proc_id", "") or "")
        if _row_identity(row) == identity or proc_id == identity:
            return row
    return None


def _is_local_legacy_tui(row: Any, session_id: str | None) -> bool:
    from sase.procs import TUI_PROC_KIND

    if getattr(row, "proc_type", None) != TUI_PROC_KIND:
        return False
    row_sid = getattr(row, "session_id", None)
    if row_sid is None:
        return True
    if session_id is None:
        return False
    return str(row_sid) == str(session_id)


def _as_blocker_kind(value: object) -> RestartBlockerKind:
    for kind in _KIND_GROUP:
        if value == kind:
            return kind
    return "session_worker"


def _item_identity(item: Any) -> str:
    for attr in ("identity", "durable_proc_id", "proc_id"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value:
            return value
        if value:
            return str(value)
    label = getattr(item, "label", None)
    return str(label) if label else ""


def _item_label(item: Any) -> str:
    label = getattr(item, "label", None)
    if callable(label):
        try:
            label = label()
        except Exception:
            label = None
    if isinstance(label, str) and label:
        return label
    display = getattr(item, "display_name", None)
    if isinstance(display, str) and display:
        return display
    from sase.ace.tui.quit_impact import overlay_row_label

    return overlay_row_label(item)


__all__ = [
    "RestartBlocker",
    "collect_restart_blockers",
    "restart_after_update",
    "restart_after_update_when_ready",
    "running_background_procs",
]
