"""Shared notification helpers for the ACE agents TUI."""

from __future__ import annotations

from collections.abc import Callable
from inspect import Parameter, getattr_static, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


TabName = Literal["artifacts", "agents", "axe"]


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


def _call_schedule_agents_refresh(app: Any) -> None:
    if getattr_static(app, "request_agents_refresh", None) is not None:
        request_refresh = getattr(app, "request_agents_refresh", None)
        if callable(request_refresh):
            request_refresh("notification", latest_only=True)
            return

    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if not callable(schedule_refresh):
        return
    if _callable_accepts_kwarg(schedule_refresh, "source"):
        schedule_refresh(source="notification")
    else:
        schedule_refresh()


def _agent_artifact_dir(agent: Any) -> Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    artifacts_dir = get_artifacts_dir()
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return Path(artifacts_dir)


def _resolve_notification_agent(
    app: Any,
    notification: Notification | None,
) -> Agent | None:
    if notification is None:
        return None
    try:
        from ._notification_navigation import find_agent_for_notification

        return find_agent_for_notification(app, notification)
    except Exception:
        return None


def refresh_notification_agent_from_cache(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> bool:
    """Refresh notification-driven row state without forcing disk I/O."""
    if agent is None:
        agent = _resolve_notification_agent(app, notification)
    if agent is None:
        return False

    agents_with_children = getattr(app, "_agents_with_children", None)
    refilter = getattr(app, "_refilter_agents", None)
    if (
        callable(refilter)
        and isinstance(agents_with_children, list)
        and agents_with_children
    ):
        refilter()
        return True

    try_patch = None
    if getattr_static(app, "_try_patch_agent_row", None) is not None:
        try_patch = getattr(app, "_try_patch_agent_row", None)
    if callable(try_patch):
        try:
            return bool(try_patch(agent))
        except Exception:
            return False
    return False


def _completion_notification_delta_dirs(app: Any) -> list[Path]:
    snapshot = getattr(app, "_notification_snapshot_cache", None)
    notifications = getattr(snapshot, "notifications", None)
    if not isinstance(notifications, list):
        return []
    completion_keys = active_completion_agent_keys(notifications)
    if not completion_keys:
        return []

    artifact_dirs: list[Path] = []
    for agent in getattr(app, "_agents", []):
        if (agent.cl_name, agent.raw_suffix) not in completion_keys and (
            agent.cl_name,
            None,
        ) not in completion_keys:
            continue
        artifact_dir = _agent_artifact_dir(agent)
        if artifact_dir is not None:
            artifact_dirs.append(artifact_dir)
    return artifact_dirs


def request_notification_agents_refresh(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> None:
    """Request notification/completion-triggered agent reconciliation."""
    if agent is None:
        agent = _resolve_notification_agent(app, notification)

    artifact_dirs: list[Path] = []
    if agent is not None:
        artifact_dir = _agent_artifact_dir(agent)
        if artifact_dir is not None:
            artifact_dirs.append(artifact_dir)
    else:
        artifact_dirs.extend(_completion_notification_delta_dirs(app))

    if artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(artifact_dirs, source="notification")
            return

    _call_schedule_agents_refresh(app)


def prepare_disappeared_plan_notification_refresh(
    app: Any,
    previous_notifications: list[Notification],
    current_notifications: list[Notification],
) -> tuple[tuple[Path, ...], bool]:
    """Resolve disappeared plan-review rows to a bounded refresh request.

    This helper may call ``Agent.get_artifacts_dir()``, which can inspect the
    filesystem. Polling therefore invokes it on the same worker thread that
    reads the notification snapshot and only applies the returned paths on the
    Textual thread.

    Returns ``(artifact_dirs, needs_broad_fallback)``. Duplicate notifications
    for one artifact are coalesced, and unrelated notification removals are
    ignored.
    """
    current_ids = {notification.id for notification in current_notifications}
    artifact_dirs: set[Path] = set()
    needs_broad_fallback = False
    for notification in previous_notifications:
        if (
            notification.dismissed
            or notification.id in current_ids
            or notification.action not in {"PlanApproval", "EpicApproval"}
        ):
            continue
        agent = _resolve_notification_agent(app, notification)
        artifact_dir = _agent_artifact_dir(agent) if agent is not None else None
        if artifact_dir is None:
            needs_broad_fallback = True
            continue
        artifact_dirs.add(artifact_dir)
    return tuple(sorted(artifact_dirs, key=str)), needs_broad_fallback


def apply_disappeared_plan_notification_refresh(
    app: Any,
    artifact_dirs: tuple[Path, ...],
    *,
    needs_broad_fallback: bool,
) -> None:
    """Apply a worker-prepared plan-review disappearance refresh request."""
    if artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(artifact_dirs, source="notification")
        else:
            needs_broad_fallback = True
    if needs_broad_fallback:
        _call_schedule_agents_refresh(app)


def refresh_notification_agent_or_request(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> None:
    """Patch/refilter a notification-targeted row, falling back to reconcile."""
    if refresh_notification_agent_from_cache(
        app,
        agent=agent,
        notification=notification,
    ):
        return
    request_notification_agents_refresh(
        app,
        agent=agent,
        notification=notification,
    )


def active_completion_agent_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active completion notifications.

    A completion notification is identified by ``sender == "user-agent"`` and
    ``action`` in ``{"JumpToAgent", "ViewErrorReport"}`` with ``cl_name``
    present in ``action_data``. ``raw_suffix`` may be absent when the writer
    did not record one, so those rows match agents by ``cl_name`` only.

    "Active" means not yet dismissed. Default snapshots already omit
    dismissed rows, but the predicate is enforced here as well so callers
    that pass ``include_dismissed=True`` get the right projection. Silent
    rows still count: per the one-to-one contract, dismissed status is
    what gates the row, not indicator visibility.
    """
    keys: set[tuple[str, str | None]] = set()
    for n in notifications:
        if not _is_active_agent_completion_notification(n):
            continue
        cl_name = n.action_data.get("cl_name")
        if not cl_name:
            continue
        raw_suffix = n.action_data.get("raw_suffix") or None
        keys.add((cl_name, raw_suffix))
    return keys


def _is_active_agent_completion_notification(notification: Notification) -> bool:
    """Return True for active agent completion notifications."""
    if notification.sender != "user-agent":
        return False
    if notification.action not in ("JumpToAgent", "ViewErrorReport"):
        return False
    return not notification.dismissed


def agent_completion_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* targets the supplied agent key."""
    if not _is_active_agent_completion_notification(notification):
        return False
    notification_cl_name = notification.action_data.get("cl_name")
    if not notification_cl_name or notification_cl_name != cl_name:
        return False
    notification_raw_suffix = notification.action_data.get("raw_suffix") or None
    return notification_raw_suffix is None or notification_raw_suffix == raw_suffix


def unread_notification_buckets(
    notifications: list[Notification],
) -> tuple[
    list[Notification], list[Notification], list[Notification], list[Notification]
]:
    from sase.notifications import is_error, is_priority

    unread_priority: list[Notification] = []
    unread_errors: list[Notification] = []
    unread_rest: list[Notification] = []
    unread_muted: list[Notification] = []
    for n in notifications:
        if n.read or n.silent:
            continue
        if n.muted:
            unread_muted.append(n)
        elif is_error(n):
            unread_errors.append(n)
        elif is_priority(n):
            unread_priority.append(n)
        else:
            unread_rest.append(n)
    return unread_priority, unread_errors, unread_rest, unread_muted
