"""Exactly-once settlement notification for proc-owned hand-off ToolRuns."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from sase.tool.render import format_duration_ms

if TYPE_CHECKING:
    from sase.notifications.models import Notification

_UNSETTLED_STATES = frozenset({"created", "running"})
_SENDER = "tool-run"
_TAGS = ["tool-run"]
_LOCK_NAME = "tool_run_notifications"


def _settlement_notification_id(run_id: str) -> str:
    """Return the deterministic notification id for one run's settlement."""

    return str(uuid5(NAMESPACE_URL, f"sase:tool-run-settled:{run_id}"))


def _notification_is_durable(notification_id: str) -> bool:
    try:
        from sase.notifications.store import load_notifications

        return any(
            notification.id == notification_id
            for notification in load_notifications(include_dismissed=True)
        )
    except Exception:  # noqa: BLE001 - an unreadable store is not proof.
        return False


def _load_run(run_id: str) -> dict[str, Any] | None:
    from sase.core.tool_run import tool_run_show

    run = tool_run_show(run_id).get("run")
    return run if isinstance(run, dict) else None


def _eligible(run: Mapping[str, Any]) -> bool:
    return (
        bool(run.get("run_id"))
        and str(run.get("state") or "") not in _UNSETTLED_STATES
        and str(run.get("state") or "") != ""
        and str(run.get("launch_mode") or "") == "handoff"
        and str(run.get("owner_kind") or "") == "proc"
    )


def _notes(run: Mapping[str, Any], run_id: str) -> list[str]:
    tool = str(run.get("tool_name") or "") or "ad-hoc"
    state = str(run.get("state") or "")
    exit_code = run.get("exit_code")
    headline = f"Tool run {tool} {state}"
    if exit_code is not None:
        headline += f" (exit {exit_code})"
    details: list[str] = []
    cause = run.get("terminal_cause")
    if cause:
        details.append(f"cause: {cause}")
    duration = run.get("duration_ms")
    if type(duration) is int:
        details.append(f"duration: {format_duration_ms(duration)}")
    notes = [headline]
    if details:
        notes.append("; ".join(details))
    notes.append(f"sase tool show {run_id}")
    return notes


def _build_notification(
    run: Mapping[str, Any], run_id: str, notification_id: str
) -> Notification:
    from sase.core.time import get_timezone
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.tool.owner import owner_retention

    retention = owner_retention(run)
    log_path = retention.get("log_path")
    files = [str(log_path)] if log_path and retention.get("log") == "retained" else []
    return Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=_SENDER,
        notes=_notes(run, run_id),
        files=files,
        tags=normalize_notification_tags(_TAGS),
        action=None,
        action_data={"run_id": run_id, "command": f"sase tool show {run_id}"},
    )


def deliver_handoff_settlement(run: str | Mapping[str, Any]) -> str:
    """Publish the settlement notification for a proc-owned hand-off, once.

    Returns ``published``, ``already_published``, ``skipped`` (not a settled
    proc-owned hand-off), or ``failed``. Every settler (worker, proc
    settlement hook, reconcile passes) may call this: the deterministic id and
    one shared lock collapse them into a single durable notification.
    """

    try:
        if isinstance(run, str):
            loaded = _load_run(run)
            if loaded is None:
                return "skipped"
            run = loaded
        if not _eligible(run):
            return "skipped"
        run_id = str(run["run_id"])
        notification_id = _settlement_notification_id(run_id)
        from sase.core.tool_run import tools_dir
        from sase.logs._bounded import log_file_lock

        with log_file_lock(tools_dir() / _LOCK_NAME):
            if _notification_is_durable(notification_id):
                return "already_published"
            try:
                from sase.notifications.store import append_notification

                append_notification(_build_notification(run, run_id, notification_id))
            except Exception:  # noqa: BLE001 - a durable row means it was published.
                if _notification_is_durable(notification_id):
                    return "already_published"
                return "failed"
            return "published"
    except Exception:  # noqa: BLE001 - delivery is best-effort.
        return "failed"


__all__ = ["deliver_handoff_settlement"]
