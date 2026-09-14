"""Tests for the notification-store facade backed by a fake rust module."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core import notification_store_facade as facade
from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    NotificationStateUpdateWire,
)
from sase.notifications.models import Notification

from tests.test_core_facade._notification_store_helpers import (
    _fake_module,
    _notification,
)


def test_read_snapshot_rehydrates_typed_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    def fake_read(path: str, include_dismissed: bool, expire_due_snoozes: bool) -> dict:
        calls.append((path, include_dismissed, expire_due_snoozes))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "notifications": [
                {
                    "id": "n1",
                    "timestamp": "2026-04-30T12:00:00+00:00",
                    "sender": "axe",
                    "notes": ["hello"],
                    "files": [],
                    "tags": ["done"],
                    "action": "PlanApproval",
                    "action_data": {"agent_cl_name": "cl"},
                    "read": False,
                    "dismissed": False,
                    "silent": False,
                    "muted": False,
                    "snooze_until": None,
                    "resurfaced_at": "2026-04-30T13:00:00+00:00",
                }
            ],
            "counts": {"priority": 1, "rest": 0, "muted": 0},
            "expired_ids": [],
            "next_snooze_deadline": "2026-04-30T14:00:00+00:00",
            "stats": {
                "total_lines": 1,
                "blank_lines": 0,
                "invalid_json_lines": 0,
                "invalid_record_lines": 0,
                "loaded_rows": 1,
                "dismissed_filtered": 0,
            },
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    snapshot = facade.read_notifications_snapshot(
        "/tmp/notifications.jsonl", include_dismissed=True, expire_due_snoozes=True
    )

    assert calls == [("/tmp/notifications.jsonl", True, True)]
    assert snapshot.counts.priority == 1
    assert snapshot.notifications[0].id == "n1"
    assert snapshot.notifications[0].tags == ["done"]
    assert snapshot.notifications[0].resurfaced_at == "2026-04-30T13:00:00+00:00"
    assert snapshot.next_snooze_deadline == "2026-04-30T14:00:00+00:00"
    assert isinstance(snapshot.notifications[0], Notification)


def test_read_current_snapshot_uses_canonical_expiring_core_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    def fake_read(path: str, include_dismissed: bool, expire: bool) -> dict:
        calls.append((path, include_dismissed, expire))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "next_snooze_deadline": None,
            "stats": {},
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    snapshot = facade.read_current_notifications_snapshot(
        "/tmp/notifications.jsonl", include_dismissed=True
    )

    assert calls == [("/tmp/notifications.jsonl", True, True)]
    assert snapshot.next_snooze_deadline is None


def test_missing_notification_binding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_module(monkeypatch)

    with pytest.raises(AttributeError, match="read_notifications_snapshot"):
        facade.read_notifications_snapshot("/tmp/notifications.jsonl")


def test_schema_mismatch_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(_path: str, _include: bool, _expire: bool) -> dict:
        return {
            "schema_version": 999,
            "notifications": [],
            "counts": {"priority": 0, "rest": 0, "muted": 0},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, read_notifications_snapshot=fake_read)

    with pytest.raises(ValueError, match="notification store wire schema mismatch"):
        facade.read_notifications_snapshot("/tmp/notifications.jsonl")


def test_apply_state_update_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_apply_counts(path: str, update: dict[str, Any]) -> dict:
        calls.append((path, update))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 2,
            "changed_count": 2,
            "appended_count": 0,
            "rewritten": True,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, apply_notification_state_update_counts=fake_apply_counts)

    outcome = facade.apply_notification_state_update_counts(
        "/tmp/notifications.jsonl",
        NotificationStateUpdateWire(kind="mark_all_read"),
    )

    assert calls == [
        ("/tmp/notifications.jsonl", {"kind": "mark_all_read"}),
    ]
    assert outcome.changed_count == 2
    assert outcome.notifications == []


def test_append_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_append_counts(path: str, notification: dict[str, Any]) -> dict:
        calls.append((path, notification))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 0,
            "changed_count": 0,
            "appended_count": 1,
            "rewritten": False,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, append_notification_counts=fake_append_counts)

    outcome = facade.append_notification_counts(
        "/tmp/notifications.jsonl", _notification("n1", sender="axe")
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/notifications.jsonl"
    assert calls[0][1]["id"] == "n1"
    assert outcome.appended_count == 1
    assert outcome.notifications == []


def test_rewrite_counts_uses_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_rewrite_counts(path: str, notifications: list[dict[str, Any]]) -> dict:
        calls.append((path, notifications))
        return {
            "schema_version": NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            "matched_count": 2,
            "changed_count": 2,
            "appended_count": 0,
            "rewritten": True,
            "notifications": [],
            "counts": {},
            "expired_ids": [],
            "stats": {},
        }

    _fake_module(monkeypatch, rewrite_notifications_counts=fake_rewrite_counts)

    outcome = facade.rewrite_notifications_counts(
        "/tmp/notifications.jsonl",
        [_notification("n1"), _notification("n2")],
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/notifications.jsonl"
    assert [n["id"] for n in calls[0][1]] == ["n1", "n2"]
    assert outcome.rewritten is True
    assert outcome.matched_count == 2
    assert outcome.notifications == []
