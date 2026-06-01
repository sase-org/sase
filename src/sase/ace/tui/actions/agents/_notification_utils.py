"""Shared notification helpers for the ACE agents TUI."""

from __future__ import annotations

from collections.abc import Callable
from inspect import Parameter, getattr_static, signature
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification


TabName = Literal["changespecs", "agents", "axe"]


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


def request_notification_agents_refresh(app: Any) -> None:
    """Debounce notification/completion-triggered agent refreshes."""
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
