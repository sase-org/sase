"""Shared helpers for notification-toast tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    NotificationTagTab,
    SNOOZED_TAB_KEY,
)
from sase.core.notification_store_facade import classify_notification_tabs
from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    _NotificationCountsWire,
    NotificationStoreSnapshotWire,
)
from sase.core.time import get_timezone
from sase.notifications import is_priority
from sase.notifications.models import Notification


def _make(
    *,
    action: str | None = None,
    notes: list[str] | None = None,
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
    id: str | None = None,
    read: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
    resurfaced_at: str | None = None,
    timestamp: str | None = None,
) -> Notification:
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=timestamp or datetime.now(get_timezone()).isoformat(),
        sender="test",
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
        resurfaced_at=resurfaced_at,
    )


class _FakeApp(LifecycleMixin, AgentNotificationMixin):
    """Minimal scaffolding to exercise the polling delta logic."""

    def __init__(self) -> None:
        self._last_unread_ids: set[str] = set()
        self._delivered_notification_activity_cursors: set[tuple[str, str]] = set()
        self._agents: list = []
        self._agent_status_overrides = {}
        self._agent_pre_question_status = {}
        self.notify = MagicMock()  # type: ignore[assignment]
        self._bell_rung = 0
        self._indicator_tabs: list[NotificationTagTab] = []
        self._indicator_count: int | None = None
        self._auto_dismissed_notification_ids: set[str] = set()

    def _ring_tmux_bell(self) -> None:  # type: ignore[override]
        self._bell_rung += 1

    def _apply_notification_status_overrides(  # type: ignore[override]
        self,
        unread: list[Notification],
        **_kwargs: object,
    ) -> set[str]:
        # Status overrides aren't exercised in these tests; callers can report
        # selected IDs as auto-dismissed to exercise polling suppression.
        del unread
        return set(self._auto_dismissed_notification_ids)

    def _indicator_tab_count(self, tag: str | None) -> int:
        """Return the count the indicator was last handed for one panel tab."""
        return sum(tab.count for tab in self._indicator_tabs if tab.tag == tag)

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs

        def _set_tabs(tabs: Any) -> None:
            self._indicator_tabs = list(tabs)
            # What the badge would show: the deferred tabs never contribute.
            self._indicator_count = sum(
                tab.count
                for tab in self._indicator_tabs
                if tab.tag not in (MUTED_TAB_KEY, SNOOZED_TAB_KEY)
            )

        return SimpleNamespace(set_tabs=_set_tabs)


def _snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    next_snooze_deadline: str | None = None,
) -> NotificationStoreSnapshotWire:
    priority_count = 0
    rest_count = 0
    muted_count = 0
    for notification in notifications:
        if notification.read or notification.silent:
            continue
        if notification.muted:
            muted_count += 1
        elif is_priority(notification):
            priority_count += 1
        else:
            rest_count += 1
    counts = _NotificationCountsWire(
        priority=priority_count,
        rest=rest_count,
        muted=muted_count,
    )
    # The real store classifies the same rows it counts, skipping read and
    # silent ones; mirror that here so the fixture cannot drift from it.
    classification = classify_notification_tabs(
        [n for n in notifications if not n.read and not n.silent]
    )
    return NotificationStoreSnapshotWire(
        schema_version=NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
        notifications=list(notifications),
        counts=counts,
        tabs=list(classification.tabs),
        expired_ids=expired_ids or [],
        next_snooze_deadline=next_snooze_deadline,
    )


def _patch_snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    next_snooze_deadline: str | None = None,
) -> Any:
    return patch(
        "sase.notifications.read_notification_snapshot",
        return_value=_snapshot(
            notifications,
            expired_ids=expired_ids,
            next_snooze_deadline=next_snooze_deadline,
        ),
    )
