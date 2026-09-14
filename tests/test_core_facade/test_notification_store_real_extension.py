"""Tests for the notification-store facade against the real rust extension."""

from __future__ import annotations

import dataclasses
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.core import notification_store_facade as facade
from sase.core.notification_store_wire import (
    NotificationStateUpdateWire,
    notification_store_wire_to_json_dict,
)
from sase.core.time import get_timezone

from tests.test_core_facade._notification_store_helpers import (
    FIXTURE_PATH,
    _notification,
    _skip_without_notification_bindings,
)


def test_real_extension_round_trips_store_operations(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"

    append = facade.append_notification(
        path, _notification("n1", sender="axe", tags=["done", "review"])
    )
    assert append.appended_count == 1
    assert append.notifications[0].id == "n1"
    assert append.notifications[0].tags == ["done", "review"]

    mark = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_read", id="n1")
    )
    assert mark.matched_count == 1
    assert mark.changed_count == 1
    assert mark.notifications[0].read is True

    snapshot = facade.read_notifications_snapshot(path)
    assert snapshot.counts.priority == 0
    assert snapshot.notifications[0].read is True
    assert snapshot.notifications[0].tags == ["done", "review"]

    rewrite = facade.rewrite_notifications(path, [_notification("n2")])
    assert rewrite.rewritten is True
    assert [n.id for n in rewrite.notifications] == ["n2", "n1"]


def test_real_extension_round_trips_bulk_mute_and_snooze(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path, [_notification("n1"), _notification("n2"), _notification("n3")]
    )

    muted = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_many_muted",
            ids=("n1", "missing", "n2", "n1"),
            muted=True,
        ),
    )
    assert muted.matched_count == 2
    assert muted.changed_count == 2
    assert {n.id for n in muted.notifications if n.muted} == {"n1", "n2"}

    deadline = datetime.now(get_timezone()) + timedelta(minutes=15)
    snoozed = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_many_snoozed",
            ids=("n2", "n3"),
            until=deadline.isoformat(),
        ),
    )
    assert snoozed.matched_count == 2
    by_id = {n.id: n for n in snoozed.notifications}
    normalized_deadline = deadline.astimezone(UTC).isoformat()
    assert by_id["n2"].snooze_until == normalized_deadline
    assert by_id["n3"].snooze_until == normalized_deadline


def test_real_extension_mark_tab_read_scopes_to_one_tab(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path,
        [
            _notification("a1", tags=["alpha"]),
            _notification("a2", tags=["alpha"]),
            _notification("b1", tags=["beta"]),
        ],
    )

    outcome = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_tab_read", tab_key="alpha")
    )
    assert outcome.matched_count == 2
    assert outcome.changed_count == 2

    snapshot = facade.read_notifications_snapshot(path)
    by_id = {n.id: n for n in snapshot.notifications}
    assert by_id["a1"].read is True
    assert by_id["a2"].read is True
    assert by_id["b1"].read is False

    repeat = facade.apply_notification_state_update(
        path, NotificationStateUpdateWire(kind="mark_tab_read", tab_key="alpha")
    )
    assert repeat.matched_count == 0
    assert repeat.changed_count == 0


def test_real_extension_append_counts_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("append_notification_counts")
    path = tmp_path / "notifications.jsonl"

    outcome = facade.append_notification_counts(path, _notification("n1", sender="axe"))

    assert outcome.appended_count == 1
    assert outcome.notifications == []
    assert outcome.stats.loaded_rows == 0
    snapshot = facade.read_notifications_snapshot(path)
    assert [n.id for n in snapshot.notifications] == ["n1"]


def test_real_extension_rewrite_counts_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("rewrite_notifications_counts")
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1"))

    outcome = facade.rewrite_notifications_counts(
        path, [_notification("n1", read=True), _notification("n2")]
    )

    assert outcome.rewritten is True
    assert outcome.matched_count == 2
    assert outcome.changed_count == 2
    assert outcome.notifications == []
    snapshot = facade.read_notifications_snapshot(path)
    assert {n.id for n in snapshot.notifications} == {"n1", "n2"}


def test_real_extension_counts_update_omits_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings("apply_notification_state_update_counts")
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1", sender="axe"))

    outcome = facade.apply_notification_state_update_counts(
        path, NotificationStateUpdateWire(kind="mark_all_read")
    )

    assert outcome.changed_count == 1
    assert outcome.notifications == []
    assert outcome.counts.priority == 0
    assert outcome.stats.loaded_rows == 0
    assert facade.read_notifications_snapshot(path).notifications[0].read is True


def test_real_extension_reads_phase1_contract_fixture(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    shutil.copyfile(FIXTURE_PATH, path)

    active = facade.read_notifications_snapshot(path)
    all_rows = facade.read_notifications_snapshot(path, include_dismissed=True)

    assert len(active.notifications) == 12
    assert len(all_rows.notifications) == 13
    assert active.stats.invalid_json_lines == 1
    assert active.stats.invalid_record_lines == 1
    assert active.counts.priority == 4
    assert active.counts.errors == 2
    assert active.counts.muted == 2
    valid_full = next(n for n in all_rows.notifications if n.id == "valid-full")
    assert valid_full.tags == ["done", "review"]


def test_real_extension_snapshot_can_expire_due_snoozes(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    past = (datetime.now(get_timezone()) - timedelta(minutes=1)).isoformat()
    facade.append_notification(
        path, _notification("snoozed", muted=True, snooze_until=past)
    )

    snapshot = facade.read_notifications_snapshot(path, expire_due_snoozes=True)

    assert snapshot.expired_ids == ["snoozed"]
    assert snapshot.notifications[0].muted is False
    assert snapshot.notifications[0].read is False
    assert snapshot.notifications[0].snooze_until is None
    assert snapshot.notifications[0].resurfaced_at is not None
    assert snapshot.next_snooze_deadline is None


def test_real_extension_validates_and_normalizes_snooze_updates(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.rewrite_notifications(
        path, [_notification("active"), _notification("other")]
    )

    normalized = facade.apply_notification_state_update(
        path,
        NotificationStateUpdateWire(
            kind="mark_snoozed",
            id="active",
            until="2099-01-01T04:00:00-05:00",
        ),
    )
    active = next(row for row in normalized.notifications if row.id == "active")
    assert active.snooze_until == "2099-01-01T09:00:00+00:00"
    assert normalized.next_snooze_deadline == "2099-01-01T09:00:00+00:00"

    with pytest.raises(ValueError, match="timezone-aware"):
        facade.apply_notification_state_update(
            path,
            NotificationStateUpdateWire(
                kind="mark_many_snoozed",
                ids=("active", "other"),
                until="2099-01-01T09:00:00",
            ),
        )
    snapshot = facade.read_notifications_snapshot(path)
    other = next(row for row in snapshot.notifications if row.id == "other")
    assert other.snooze_until is None


def test_store_write_invalidates_snapshot_cache(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    facade.append_notification(path, _notification("n1"))
    first = facade.read_current_notifications_snapshot(path)
    assert [row.id for row in first.notifications] == ["n1"]

    facade.append_notification(path, _notification("n2"))
    second = facade.read_current_notifications_snapshot(path)
    assert {row.id for row in second.notifications} == {"n1", "n2"}


def test_compact_preserves_unread_and_actionable_notifications(tmp_path: Path) -> None:
    _skip_without_notification_bindings()
    path = tmp_path / "notifications.jsonl"
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    unread = _notification("unread")
    actionable = _notification("actionable", action="PlanApproval")
    recent_dismissed = dataclasses.replace(
        _notification("recent-dismissed", read=True),
        dismissed=True,
        timestamp=recent,
    )
    snoozed_dismissed = dataclasses.replace(
        _notification(
            "snoozed-dismissed",
            muted=True,
            snooze_until=future,
        ),
        dismissed=True,
        timestamp=old,
    )
    old_dismissed = [
        dataclasses.replace(
            _notification(f"old-dismissed-{index:04d}", read=True),
            dismissed=True,
            timestamp=old,
        )
        for index in range(1_001)
    ]
    rows = [unread, actionable, recent_dismissed, snoozed_dismissed, *old_dismissed]
    path.write_text(
        "".join(
            json.dumps(notification_store_wire_to_json_dict(row)) + "\n" for row in rows
        ),
        encoding="utf-8",
    )

    outcome = facade.compact_notification_store(path)

    assert outcome.archived_count == 1_001
    assert outcome.live_bytes_after < outcome.live_bytes_before
    live = facade.read_notifications_snapshot(path, include_dismissed=True)
    live_ids = {row.id for row in live.notifications}
    assert {"unread", "actionable", "recent-dismissed", "snoozed-dismissed"} <= live_ids
    assert "old-dismissed-0000" not in live_ids
    unread_row = next(row for row in live.notifications if row.id == "unread")
    actionable_row = next(row for row in live.notifications if row.id == "actionable")
    assert unread_row.read is False
    assert unread_row.dismissed is False
    assert actionable_row.action == "PlanApproval"
    archive = Path(outcome.archive_path)
    archived_ids = {
        json.loads(line)["id"]
        for line in archive.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "old-dismissed-0000" in archived_ids
    assert "unread" not in archived_ids
    assert "actionable" not in archived_ids
