"""End-to-end snooze regression matrix across the real store bindings.

These tests deliberately avoid mocking the notification store. They drive the
Rust-backed JSONL store through the same public surfaces the long-lived
consumers use — the ACE snapshot read, the CLI catalog, and the mobile bridge —
and assert the persisted state, activity ordering, next-deadline projection,
concurrency behavior, and per-consumer delivery cursors together.

Elapsed wall-clock time is simulated by moving every persisted deadline earlier
by the same amount, which is equivalent to advancing "now" and keeps the
assertions deterministic without sleeping on a real deadline.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sase.core.time import get_timezone
from sase.integrations.mobile_notifications import read_mobile_notification_snapshot
from sase.notifications.catalog import list_notification_infos
from sase.notifications.models import (
    Notification,
    encode_notification_activity_cursor,
    notification_activity_at,
    notification_is_newer_than_activity_cursor,
)
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_dismissed,
    mark_many_snoozed,
    mark_muted,
    mark_snoozed,
    read_current_notification_snapshot,
    read_notification_snapshot,
    rewrite_notifications,
)

from .helpers import make_notification


def _jsonl_path(temp_notifications_dir: Path) -> Path:
    return temp_notifications_dir / "notifications" / "notifications.jsonl"


def _jsonl_rows(temp_notifications_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the exact persisted JSONL rows keyed by notification id."""
    path = _jsonl_path(temp_notifications_dir)
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        rows[str(record["id"])] = record
    return rows


def _jsonl_line_count(temp_notifications_dir: Path) -> int:
    path = _jsonl_path(temp_notifications_dir)
    return len(
        [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    )


def _advance_clock(seconds: float) -> None:
    """Simulate ``seconds`` of elapsed wall-clock time for every deadline."""
    rows = load_notifications(include_dismissed=True)
    shifted = False
    for row in rows:
        if not row.snooze_until:
            continue
        deadline = datetime.fromisoformat(row.snooze_until)
        row.snooze_until = (
            (deadline - timedelta(seconds=seconds)).astimezone(UTC).isoformat()
        )
        shifted = True
    if shifted:
        rewrite_notifications(rows)


def _seed_row(
    *,
    notification_id: str,
    minutes_ago: float = 0.0,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    muted: bool = False,
) -> Notification:
    notification = make_notification(id=notification_id, read=read, silent=silent)
    notification.timestamp = (
        datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)
    ).isoformat()
    notification.muted = muted
    append_notification(notification)
    if dismissed:
        assert mark_dismissed(notification_id) is True
    return notification


def _future(seconds: float) -> datetime:
    return datetime.now(get_timezone()) + timedelta(seconds=seconds)


class TestSnoozeStateMatrix:
    """Scenario 1: exact persisted state across every canonical transition."""

    def test_mixed_row_classes_expire_to_one_activity_generation(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="active", minutes_ago=40)
        _seed_row(notification_id="read-row", minutes_ago=30, read=True)
        _seed_row(notification_id="dismissed", minutes_ago=20, dismissed=True)
        _seed_row(notification_id="silent-row", minutes_ago=10, silent=True)
        _seed_row(notification_id="permanent-mute", minutes_ago=5, muted=True)

        deadline = _future(3600)
        assert mark_many_snoozed(["active", "read-row", "silent-row"], deadline) == 3
        # A dismissed row and a missing row can never take a deadline.
        assert mark_snoozed("dismissed", deadline) is False
        assert mark_snoozed("does-not-exist", deadline) is False

        pending = read_current_notification_snapshot()
        assert pending.expired_ids == []
        assert pending.next_snooze_deadline is not None
        assert datetime.fromisoformat(
            pending.next_snooze_deadline
        ) == deadline.astimezone(UTC)
        # `active` and `read-row` are muted-unread; `silent-row` never counts.
        assert pending.counts.muted == 2
        assert pending.counts.rest == 0

        before = _jsonl_rows(temp_notifications_dir)
        assert before["permanent-mute"]["muted"] is True
        assert before["permanent-mute"]["snooze_until"] is None
        assert before["dismissed"]["snooze_until"] is None
        assert before["read-row"]["read"] is True

        _advance_clock(3601)
        snapshot = read_current_notification_snapshot(include_dismissed=True)

        assert set(snapshot.expired_ids) == {"active", "read-row", "silent-row"}
        assert snapshot.next_snooze_deadline is None

        rows = _jsonl_rows(temp_notifications_dir)
        assert _jsonl_line_count(temp_notifications_dir) == 5

        resurfaced = {rows[row_id]["resurfaced_at"] for row_id in snapshot.expired_ids}
        assert len(resurfaced) == 1
        stamp = resurfaced.pop()
        assert stamp is not None

        for row_id in ("active", "read-row", "silent-row"):
            row = rows[row_id]
            assert row["muted"] is False
            assert row["snooze_until"] is None
            assert row["read"] is False
            assert row["resurfaced_at"] == stamp
            # The original creation time is immutable.
            assert row["timestamp"] == before[row_id]["timestamp"]

        assert rows["dismissed"]["dismissed"] is True
        assert rows["dismissed"]["resurfaced_at"] is None
        assert rows["permanent-mute"]["muted"] is True
        assert rows["permanent-mute"]["snooze_until"] is None
        assert rows["permanent-mute"]["resurfaced_at"] is None

        # The resurfaced generation is the newest activity even though the
        # rows are the oldest by creation time.
        visible = read_current_notification_snapshot()
        by_id = {row.id: row for row in visible.notifications}
        assert notification_activity_at(by_id["active"]) == stamp
        assert notification_activity_at(by_id["permanent-mute"]) == (
            by_id["permanent-mute"].timestamp
        )

        # A second read is idempotent: no new expiry generation.
        again = read_current_notification_snapshot(include_dismissed=True)
        assert again.expired_ids == []
        assert _jsonl_rows(temp_notifications_dir) == rows

    def test_distinct_deadlines_expire_in_order(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="first", minutes_ago=10)
        _seed_row(notification_id="second", minutes_ago=10)

        early = _future(900)
        late = _future(3600)
        assert mark_snoozed("first", early) is True
        assert mark_snoozed("second", late) is True

        pending = read_current_notification_snapshot()
        assert datetime.fromisoformat(pending.next_snooze_deadline or "") == (
            early.astimezone(UTC)
        )

        _advance_clock(901)
        first_pass = read_current_notification_snapshot()
        assert first_pass.expired_ids == ["first"]
        assert datetime.fromisoformat(first_pass.next_snooze_deadline or "") == (
            late.astimezone(UTC) - timedelta(seconds=901)
        )

        _advance_clock(2700)
        second_pass = read_current_notification_snapshot()
        assert second_pass.expired_ids == ["second"]
        assert second_pass.next_snooze_deadline is None

        rows = _jsonl_rows(temp_notifications_dir)
        assert rows["first"]["resurfaced_at"] < rows["second"]["resurfaced_at"]

    def test_resnooze_replaces_the_single_scheduled_deadline(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="row", minutes_ago=5)
        assert mark_snoozed("row", _future(3600)) is True
        earlier = _future(600)
        assert mark_snoozed("row", earlier) is True

        rows = _jsonl_rows(temp_notifications_dir)
        assert rows["row"]["snooze_until"] == earlier.astimezone(UTC).isoformat()
        snapshot = read_current_notification_snapshot()
        assert datetime.fromisoformat(snapshot.next_snooze_deadline or "") == (
            earlier.astimezone(UTC)
        )

        _advance_clock(601)
        expired = read_current_notification_snapshot()
        assert expired.expired_ids == ["row"]

    def test_unmute_and_dismiss_cancel_without_a_later_generation(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="unmuted", minutes_ago=5, read=True)
        _seed_row(notification_id="dismissed-later", minutes_ago=5)
        deadline = _future(600)
        assert mark_many_snoozed(["unmuted", "dismissed-later"], deadline) == 2

        assert mark_muted("unmuted", False) is True
        assert mark_dismissed("dismissed-later") is True

        rows = _jsonl_rows(temp_notifications_dir)
        assert rows["unmuted"]["muted"] is False
        assert rows["unmuted"]["snooze_until"] is None
        # Explicit unmute is not an expiry: read state survives untouched.
        assert rows["unmuted"]["read"] is True
        assert rows["unmuted"]["resurfaced_at"] is None
        assert rows["dismissed-later"]["snooze_until"] is None

        _advance_clock(601)
        snapshot = read_current_notification_snapshot(include_dismissed=True)
        assert snapshot.expired_ids == []
        assert snapshot.next_snooze_deadline is None
        after = _jsonl_rows(temp_notifications_dir)
        assert after["unmuted"]["read"] is True
        assert after["unmuted"]["resurfaced_at"] is None
        assert after["dismissed-later"]["resurfaced_at"] is None

    def test_new_writes_reject_past_and_naive_deadlines(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="row", minutes_ago=5)

        with pytest.raises(Exception, match="future"):
            mark_snoozed("row", datetime.now(get_timezone()) - timedelta(minutes=1))
        with pytest.raises(Exception, match="timezone-aware"):
            mark_snoozed("row", datetime.now().replace(tzinfo=None))
        with pytest.raises(Exception, match="future"):
            mark_many_snoozed(
                ["row"], datetime.now(get_timezone()) - timedelta(minutes=1)
            )

        rows = _jsonl_rows(temp_notifications_dir)
        assert rows["row"]["snooze_until"] is None
        assert rows["row"]["muted"] is False

    def test_legacy_malformed_deadline_resurfaces_immediately(
        self, temp_notifications_dir: Path
    ) -> None:
        legacy = make_notification(id="legacy")
        legacy.muted = True
        legacy.snooze_until = "2026-08-01 09:00:00"  # naive, non-RFC-3339
        append_notification(legacy)

        # A raw audit read never mutates time-driven state.
        audit = read_notification_snapshot()
        assert audit.expired_ids == []
        assert _jsonl_rows(temp_notifications_dir)["legacy"]["muted"] is True

        snapshot = read_current_notification_snapshot()
        assert snapshot.expired_ids == ["legacy"]
        row = _jsonl_rows(temp_notifications_dir)["legacy"]
        assert row["muted"] is False
        assert row["snooze_until"] is None
        assert row["resurfaced_at"] is not None


class TestConcurrentConsumers:
    """Scenario 2: concurrent consumers converge on one storage state."""

    def test_concurrent_reads_expire_once_and_stay_observable(
        self, temp_notifications_dir: Path
    ) -> None:
        ids = [f"row-{index}" for index in range(6)]
        for notification_id in ids:
            _seed_row(notification_id=notification_id, minutes_ago=15)
        assert mark_many_snoozed(ids, _future(600)) == len(ids)
        _advance_clock(601)

        def ace_read() -> list[str]:
            return list(read_current_notification_snapshot().expired_ids)

        def mobile_read() -> list[str]:
            return list(read_mobile_notification_snapshot().expired_ids)

        def appender() -> list[str]:
            fresh = make_notification(id="appended-during-expiry")
            append_notification(fresh)
            return []

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(ace_read),
                pool.submit(mobile_read),
                pool.submit(ace_read),
                pool.submit(mobile_read),
                pool.submit(appender),
            ]
            observed = [future.result() for future in futures]

        flattened = [row_id for result in observed for row_id in result]
        # `expired_ids` is transition metadata: exactly one reader wins each row.
        assert sorted(flattened) == sorted(ids)

        rows = _jsonl_rows(temp_notifications_dir)
        assert len(rows) == len(ids) + 1
        assert "appended-during-expiry" in rows
        assert _jsonl_line_count(temp_notifications_dir) == len(ids) + 1

        # The persistent fields make the transition observable for every
        # consumer, including the ones that lost the expiry race.
        for notification_id in ids:
            row = rows[notification_id]
            assert row["muted"] is False
            assert row["read"] is False
            assert row["snooze_until"] is None
            assert row["resurfaced_at"] is not None

        assert read_current_notification_snapshot().expired_ids == []
        assert read_mobile_notification_snapshot().expired_ids == []

    def test_each_consumer_cursor_delivers_one_resurface_generation(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="delivered", minutes_ago=120)
        _seed_row(notification_id="newer", minutes_ago=1)

        delivered = {row.id: row for row in load_notifications()}["delivered"]
        # A transport delivered the original event and advanced its cursor.
        cursor = encode_notification_activity_cursor(delivered)
        assert notification_is_newer_than_activity_cursor(delivered, cursor) is False

        assert mark_snoozed("delivered", _future(600)) is True
        _advance_clock(601)
        assert read_current_notification_snapshot().expired_ids == ["delivered"]

        rows = {row.id: row for row in load_notifications()}
        assert notification_is_newer_than_activity_cursor(rows["delivered"], cursor)

        # Delivering the resurfaced generation advances the cursor exactly once.
        cursor = encode_notification_activity_cursor(rows["delivered"])
        rows = {row.id: row for row in load_notifications()}
        assert (
            notification_is_newer_than_activity_cursor(rows["delivered"], cursor)
            is False
        )

    def test_equal_activity_timestamps_do_not_hide_one_another(
        self, temp_notifications_dir: Path
    ) -> None:
        _seed_row(notification_id="row-a", minutes_ago=30)
        _seed_row(notification_id="row-b", minutes_ago=30)
        assert mark_many_snoozed(["row-a", "row-b"], _future(600)) == 2
        _advance_clock(601)
        assert sorted(read_current_notification_snapshot().expired_ids) == [
            "row-a",
            "row-b",
        ]

        rows = {row.id: row for row in load_notifications()}
        assert rows["row-a"].resurfaced_at == rows["row-b"].resurfaced_at

        first, second = sorted((rows["row-a"], rows["row-b"]), key=lambda row: row.id)
        cursor = encode_notification_activity_cursor(first)
        # The ID tie-breaker keeps the equal-timestamp sibling deliverable.
        assert notification_is_newer_than_activity_cursor(second, cursor) is True
        assert notification_is_newer_than_activity_cursor(first, cursor) is False


class TestResurfacedRowIsRecentActivity:
    """Scenario 3: an old row leads the first limited page on every surface."""

    def test_old_row_leads_limited_ace_cli_and_mobile_pages(
        self, temp_notifications_dir: Path
    ) -> None:
        old = _seed_row(notification_id="old", minutes_ago=60 * 24 * 30)
        for index in range(3):
            _seed_row(notification_id=f"recent-{index}", minutes_ago=index + 1)

        pre_expiry_cursor = encode_notification_activity_cursor(
            {row.id: row for row in load_notifications()}["recent-0"]
        )

        assert mark_snoozed("old", _future(600)) is True
        _advance_clock(601)
        assert read_current_notification_snapshot().expired_ids == ["old"]

        cli_page = list_notification_infos(limit=1)
        assert [info.id for info in cli_page] == ["old"]
        assert cli_page[0].timestamp == old.timestamp
        assert cli_page[0].resurfaced_at is not None

        mobile_page = read_mobile_notification_snapshot(limit=1)
        assert [row.id for row in mobile_page.rows] == ["old"]
        assert mobile_page.rows[0].timestamp == old.timestamp
        assert mobile_page.rows[0].resurfaced_at is not None
        assert mobile_page.next_high_water == (
            f"{mobile_page.rows[0].resurfaced_at}|old"
        )

        newer_than_page = read_mobile_notification_snapshot(
            newer_than=pre_expiry_cursor
        )
        assert "old" in [row.id for row in newer_than_page.rows]

        # ACE's modal list uses the same activity ordering.
        from sase.ace.tui.modals.notification_modal import NotificationModal

        ace_rows = list(read_current_notification_snapshot().notifications)
        modal = NotificationModal(ace_rows)
        options = modal._create_notification_options()
        assert ace_rows[int(str(options[0].id))].id == "old"
