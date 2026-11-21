"""Legacy per-revision row migration tests for the remote attention inbox.

Split from ``tests.test_dispatch_attention_inbox``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

from sase.dispatch import attention_inbox
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications, rewrite_notifications
from tests._dispatch_attention_inbox_helpers import (
    INSTALLATION_ID,
    OBSERVED_AT,
    entry,
    inbox_notification_store_file,  # noqa: F401 (registers the notification_store_file fixture)
    response,
)

__all__ = [
    "test_legacy_auto_dismissal_does_not_carry_to_the_stable_row",
    "test_legacy_dismissal_of_an_older_revision_does_not_hide_a_new_one",
    "test_legacy_undismissed_row_folds_into_the_stable_row",
    "test_legacy_user_dismissal_carries_to_the_stable_row",
]


def _seed_legacy_row(
    *,
    revision: int,
    request_id: str = "gate-00000001",
    read: bool = False,
    dismissed: bool = False,
    auto_dismissed: bool = False,
    muted: bool = False,
    timestamp: str = "2026-05-01T00:00:00+00:00",
) -> Notification:
    """Build a per-revision row the way the reconciler wrote it before the
    stable request key."""
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=revision, request_id=request_id)]),
        now_unix=OBSERVED_AT,
    )
    stable = next(
        row
        for row in load_notifications(include_dismissed=True)
        if row.action_data.get(
            attention_inbox.REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY
        )
        == request_id
    )
    legacy_key = f"remote-attention:{INSTALLATION_ID}:{request_id}:{revision}"
    action_data = dict(stable.action_data)
    if auto_dismissed:
        action_data[attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY] = (
            "true"
        )
    legacy = dataclasses.replace(
        stable,
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"sase:{legacy_key}")),
        dedup_key=legacy_key,
        timestamp=timestamp,
        read=read,
        dismissed=dismissed,
        muted=muted,
        action_data=action_data,
    )
    others = [
        row for row in load_notifications(include_dismissed=True) if row != stable
    ]
    _replace_store([*others, legacy])
    return legacy


def _replace_store(rows: list[Notification]) -> None:
    from sase.notifications import store as notification_store

    Path(notification_store.NOTIFICATIONS_FILE).unlink()
    rewrite_notifications(rows)


def _stable_row(request_id: str = "gate-00000001") -> Notification:
    stable_key = f"remote-attention:{INSTALLATION_ID}:{request_id}"
    [row] = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.dedup_key == stable_key
    ]
    return row


def test_legacy_user_dismissal_carries_to_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    legacy = _seed_legacy_row(revision=1, read=True, dismissed=True, muted=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 0
    assert load_notifications() == []
    stable = _stable_row()
    assert stable.id != legacy.id
    assert stable.dismissed is True
    assert stable.read is True
    assert stable.muted is True
    assert stable.timestamp == legacy.timestamp
    [untouched] = [
        row for row in load_notifications(include_dismissed=True) if row.id == legacy.id
    ]
    assert untouched == legacy

    # The migration happens once: the next pass writes nothing.
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )
    assert outcome.changed is False


def test_legacy_undismissed_row_folds_into_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    legacy = _seed_legacy_row(revision=1, read=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 1
    [active] = load_notifications()
    assert active.dedup_key == f"remote-attention:{INSTALLATION_ID}:gate-00000001"
    assert active.read is True
    [folded] = [
        row for row in load_notifications(include_dismissed=True) if row.id == legacy.id
    ]
    assert folded.dismissed is True
    assert (
        folded.action_data[
            attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY
        ]
        == "true"
    )


def test_legacy_dismissal_of_an_older_revision_does_not_hide_a_new_one(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    older = _seed_legacy_row(revision=1, read=True, dismissed=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=2)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 0
    [active] = load_notifications()
    assert active.read is False
    assert (
        active.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    [kept] = [
        row for row in load_notifications(include_dismissed=True) if row.id == older.id
    ]
    assert kept == older


def test_legacy_auto_dismissal_does_not_carry_to_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    _seed_legacy_row(revision=1, read=True, dismissed=True, auto_dismissed=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 1
    [active] = load_notifications()
    assert active.read is False
    assert active.dismissed is False
