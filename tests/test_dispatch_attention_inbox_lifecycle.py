"""Create, dismiss, and revision-resurface tests for the remote attention inbox.

Split from ``tests.test_dispatch_attention_inbox``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch import attention_inbox
from sase.notifications.store import (
    load_notifications,
    read_unread_completion_index,
    rewrite_notifications,
)
from tests._dispatch_attention_inbox_helpers import (
    INSTALLATION_ID,
    OBSERVED_AT,
    entry,
    inbox_notification_store_file,  # noqa: F401 (registers the notification_store_file fixture)
    response,
)

__all__ = [
    "test_attention_inventory_cached_repeat_never_resurfaces_user_dismissal",
    "test_attention_inventory_creates_durable_remote_attention_notification",
    "test_attention_inventory_dismissal_sticks_for_its_revision",
    "test_attention_inventory_keeps_user_dismissed_pending_request",
    "test_attention_inventory_new_revision_keeps_one_row_per_request",
    "test_attention_inventory_new_revision_resurfaces_user_dismissed_row",
    "test_attention_inventory_resurfaces_own_auto_dismissal",
    "test_attention_inventory_same_revision_re_emission_writes_nothing",
]


def test_attention_inventory_creates_durable_remote_attention_notification(
    notification_store_file: Path,
) -> None:
    del notification_store_file

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.pending == 1
    assert outcome.created == 1
    [notification] = load_notifications()
    assert notification.sender == attention_inbox.REMOTE_ATTENTION_NOTIFICATION_SENDER
    assert notification.action == attention_inbox.REMOTE_ATTENTION_NOTIFICATION_ACTION
    assert notification.action_data["panel"] == "attention"
    assert (
        notification.action_data[
            attention_inbox.REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY
        ]
        == "gate-00000001"
    )
    assert notification.read is False
    assert notification.dismissed is False
    assert notification.dedup_key == (
        f"remote-attention:{INSTALLATION_ID}:gate-00000001"
    )
    assert (
        notification.action_data[
            attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY
        ]
        == "1"
    )

    decoded = attention_inbox.remote_attention_from_notification(notification)
    assert decoded is not None
    alias, entry_payload = decoded
    assert alias == "apollo"
    assert entry_payload["request_key"]["request_id"] == "gate-00000001"


def test_attention_inventory_keeps_user_dismissed_pending_request(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    inventory = response([entry()])
    attention_inbox.reconcile_remote_attention_inbox(inventory, now_unix=OBSERVED_AT)
    [notification] = load_notifications()
    rewrite_notifications(
        [
            dataclasses.replace(
                notification,
                read=True,
                dismissed=True,
                muted=True,
                snooze_until="2026-05-12T10:00:00+00:00",
            )
        ]
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        inventory,
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 0
    assert outcome.updated == 0
    assert outcome.changed is False
    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.id == notification.id
    assert dismissed.dismissed is True
    assert dismissed.read is True
    assert dismissed.muted is True
    assert dismissed.snooze_until == "2026-05-12T10:00:00+00:00"


def test_attention_inventory_cached_repeat_never_resurfaces_user_dismissal(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )
    [notification] = load_notifications()
    rewrite_notifications(
        [dataclasses.replace(notification, read=True, dismissed=True)]
    )

    for _ in range(5):
        outcome = attention_inbox.reconcile_remote_attention_inbox(
            response([entry()], cached=True),
            now_unix=OBSERVED_AT,
        )
        assert outcome.changed is False

    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert dismissed.read is True


def test_attention_inventory_new_revision_resurfaces_user_dismissed_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )
    [old] = load_notifications()
    rewrite_notifications(
        [dataclasses.replace(old, read=True, dismissed=True, muted=True)]
    )

    revised = response([entry(revision=2)])
    revised["hosts"][0]["payload"]["observed_at_unix"] = OBSERVED_AT + 60.0
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        revised,
        now_unix=OBSERVED_AT + 60.0,
    )

    assert outcome.created == 0
    assert outcome.updated == 1
    assert outcome.dismissed == 0
    [row] = load_notifications(include_dismissed=True)
    assert row.id == old.id
    assert row.dedup_key == old.dedup_key
    assert (
        row.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    assert row.dismissed is False
    assert row.read is False
    # Local mute survives; the row's activity time moves to the new revision.
    assert row.muted is True
    assert row.timestamp == old.timestamp
    assert row.resurfaced_at is not None
    assert row.resurfaced_at > old.timestamp


def test_attention_inventory_dismissal_sticks_for_its_revision(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=2)]),
        now_unix=OBSERVED_AT,
    )
    [row] = load_notifications()
    rewrite_notifications([dataclasses.replace(row, read=True, dismissed=True)])

    for _ in range(3):
        outcome = attention_inbox.reconcile_remote_attention_inbox(
            response([entry(revision=2)]),
            now_unix=OBSERVED_AT,
        )
        assert outcome.changed is False

    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert dismissed.read is True

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=3)]),
        now_unix=OBSERVED_AT,
    )
    assert outcome.updated == 1
    [active] = load_notifications()
    assert active.id == row.id
    assert active.read is False


def test_attention_inventory_same_revision_re_emission_writes_nothing(
    notification_store_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )
    [row] = load_notifications()
    rewrite_notifications([dataclasses.replace(row, read=True, dismissed=True)])
    before = notification_store_file.read_bytes()
    generation_before = read_unread_completion_index().generation

    reconcile_calls: list[list[Any]] = []
    real_reconcile = attention_inbox.reconcile_notification_rows

    def _spying_reconcile(rows, **kwargs):  # type: ignore[no-untyped-def]
        reconcile_calls.append(list(rows))
        return real_reconcile(rows, **kwargs)

    monkeypatch.setattr(
        attention_inbox, "reconcile_notification_rows", _spying_reconcile
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT + 60.0,
    )

    assert outcome.changed is False
    assert reconcile_calls == []
    assert notification_store_file.read_bytes() == before
    assert read_unread_completion_index().generation == generation_before


def test_attention_inventory_resurfaces_own_auto_dismissal(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([]),
        now_unix=OBSERVED_AT,
    )
    assert outcome.dismissed == 1
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert (
        dismissed.action_data[
            attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY
        ]
        == "true"
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.updated == 1
    [active] = load_notifications()
    assert active.id == dismissed.id
    assert active.dismissed is False
    assert active.read is False
    assert attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY not in (
        active.action_data or {}
    )


def test_attention_inventory_new_revision_keeps_one_row_per_request(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    for revision in (1, 2, 3):
        attention_inbox.reconcile_remote_attention_inbox(
            response([entry(revision=revision)]),
            now_unix=OBSERVED_AT,
        )

    [row] = load_notifications(include_dismissed=True)
    assert row.dismissed is False
    assert (
        row.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "3"
    )
    assert attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY not in (
        row.action_data or {}
    )
