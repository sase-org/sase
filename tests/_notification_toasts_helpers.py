"""Shared helpers for notification-toast tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.core.time import get_timezone
from sase.notifications import is_priority
from sase.notifications.filters import (
    ClientNotificationSnapshot,
    NotificationCounts,
)
from sase.notifications.models import Notification


def _make(
    *,
    sender: str = "test",
    action: str | None = None,
    notes: list[str] | None = None,
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
    id: str | None = None,
    read: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
) -> Notification:
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
    )


class _FakeApp(AgentNotificationMixin):
    """Minimal scaffolding to exercise the polling delta logic."""

    def __init__(self) -> None:
        self._last_unread_ids: set[str] = set()
        self._agents: list = []
        self._agent_status_overrides = {}
        self._agent_pre_question_status = {}
        self.notify = MagicMock()  # type: ignore[assignment]
        self._bell_rung = 0
        self._indicator_priority: int | None = None
        self._indicator_rest: int | None = None
        self._indicator_count: int | None = None
        self._indicator_muted: int | None = None

    def _ring_tmux_bell(self) -> None:  # type: ignore[override]
        self._bell_rung += 1

    def _apply_notification_status_overrides(self, unread: list[Notification]) -> None:  # type: ignore[override]
        # Intentionally a no-op — status overrides aren't exercised in these tests.
        del unread

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs

        def _set_counts(priority: int, rest: int, muted: int) -> None:
            self._indicator_priority = priority
            self._indicator_rest = rest
            self._indicator_count = priority + rest
            self._indicator_muted = muted

        return SimpleNamespace(
            set_count=lambda c: setattr(self, "_indicator_count", c),
            set_counts=_set_counts,
        )


def _snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    suppressed_types: frozenset[str] = frozenset(),
) -> ClientNotificationSnapshot:
    """Build a fake client-projected snapshot for ``AgentNotificationMixin`` tests.

    Counts are recomputed on the post-suppression visible set, matching
    what :func:`read_notification_snapshot_for_client` produces in
    production.
    """
    from sase.notifications.filters import classify_notification

    if suppressed_types:
        visible = [
            n
            for n in notifications
            if not (classify_notification(n) & suppressed_types)
        ]
    else:
        visible = list(notifications)
    priority_count = 0
    error_count = 0
    rest_count = 0
    muted_count = 0
    for notification in visible:
        if notification.read or notification.silent:
            continue
        if notification.muted:
            muted_count += 1
            continue
        from sase.notifications.priority import is_error

        if is_error(notification):
            error_count += 1
        elif is_priority(notification):
            priority_count += 1
        else:
            rest_count += 1
    counts = NotificationCounts(
        priority=priority_count,
        errors=error_count,
        rest=rest_count,
        muted=muted_count,
    )
    return ClientNotificationSnapshot(
        notifications=visible,
        counts=counts,
        expired_ids=expired_ids or [],
        raw=None,
    )


def _patch_snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    suppressed_types: frozenset[str] = frozenset(),
) -> Any:
    return patch(
        "sase.notifications.read_notification_snapshot_for_client",
        return_value=_snapshot(
            notifications,
            expired_ids=expired_ids,
            suppressed_types=suppressed_types,
        ),
    )
