import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sase.core.time import get_timezone
from sase.notifications.store import (
    append_notification,
    expire_due_snoozes,
    load_notifications,
    mark_many_muted,
    mark_many_snoozed,
    mark_muted,
    mark_snoozed,
)

from .helpers import make_notification


class TestMarkMuted:
    """Tests for mark_muted()."""

    def test_mute_existing(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_muted(n.id, True) is True
        loaded = load_notifications()
        assert loaded[0].muted is True

    def test_unmute_existing(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        mark_muted(n.id, True)
        assert mark_muted(n.id, False) is True
        loaded = load_notifications()
        assert loaded[0].muted is False

    def test_default_value_mutes(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_muted(n.id) is True
        loaded = load_notifications()
        assert loaded[0].muted is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_muted("nonexistent", True) is False
        loaded = load_notifications()
        assert loaded[0].muted is False

    def test_load_record_without_muted_field(
        self, temp_notifications_dir: Path
    ) -> None:
        """A pre-existing JSONL line without ``muted`` loads as muted=False."""
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "legacy",
                        "timestamp": "2025-01-01T00:00:00",
                        "sender": "test",
                    }
                )
                + "\n"
            )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].muted is False

    def test_unmute_clears_snooze(self, temp_notifications_dir: Path) -> None:
        """``mark_muted(id, False)`` clears any pending ``snooze_until``."""
        n = make_notification()
        append_notification(n)
        deadline = datetime.now(get_timezone()) + timedelta(hours=1)
        mark_snoozed(n.id, deadline)
        loaded = load_notifications()
        assert loaded[0].muted is True
        assert loaded[0].snooze_until == deadline.isoformat()

        assert mark_muted(n.id, False) is True
        loaded = load_notifications()
        assert loaded[0].muted is False
        assert loaded[0].snooze_until is None


class TestMarkManyMuted:
    """Tests for mark_many_muted()."""

    def test_round_trip_with_missing_and_duplicate_ids(
        self, temp_notifications_dir: Path
    ) -> None:
        n1 = make_notification()
        n2 = make_notification()
        n3 = make_notification()
        for n in (n1, n2, n3):
            append_notification(n)

        assert mark_many_muted([n1.id, "missing", n2.id, n1.id]) == 2
        loaded = load_notifications()
        by_id = {n.id: n for n in loaded}
        assert by_id[n1.id].muted is True
        assert by_id[n2.id].muted is True
        assert by_id[n3.id].muted is False

    def test_empty_input_skips_rust_call(self, temp_notifications_dir: Path) -> None:
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update"
        ) as mock_update:
            assert mark_many_muted([]) == 0
        mock_update.assert_not_called()

    def test_unmute_clears_mixed_snooze_deadlines(
        self, temp_notifications_dir: Path
    ) -> None:
        n1 = make_notification()
        n2 = make_notification()
        for n in (n1, n2):
            append_notification(n)
        deadline = datetime.now(get_timezone()) + timedelta(hours=1)
        mark_many_snoozed([n1.id, n2.id], deadline)

        assert mark_many_muted([n1.id, n2.id], False) == 2
        loaded = load_notifications()
        assert all(n.muted is False for n in loaded)
        assert all(n.snooze_until is None for n in loaded)

    def test_routes_through_one_rust_update(self, temp_notifications_dir: Path) -> None:
        n1 = make_notification()
        n2 = make_notification()
        append_notification(n1)
        append_notification(n2)

        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=__import__(
                "sase.notifications.store",
                fromlist=["_rust_apply_notification_state_update"],
            )._rust_apply_notification_state_update,
        ) as mock_update:
            assert mark_many_muted([n1.id, n2.id], True) == 2

        assert mock_update.call_count == 1
        update = mock_update.call_args.args[1]
        assert update.kind == "mark_many_muted"
        assert update.ids == (n1.id, n2.id)
        assert update.muted is True


class TestMarkSnoozed:
    """Tests for ``mark_snoozed()``."""

    def test_round_trip(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        deadline = datetime.now(get_timezone()) + timedelta(minutes=15)
        assert mark_snoozed(n.id, deadline) is True
        loaded = load_notifications()
        assert loaded[0].muted is True
        assert loaded[0].snooze_until == deadline.isoformat()

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_snoozed("nonexistent", datetime.now(get_timezone())) is False
        loaded = load_notifications()
        assert loaded[0].snooze_until is None

    def test_load_record_without_snooze_until_field(
        self, temp_notifications_dir: Path
    ) -> None:
        """A pre-existing JSONL line without ``snooze_until`` loads as None."""
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "legacy",
                        "timestamp": "2025-01-01T00:00:00",
                        "sender": "test",
                        "muted": True,
                    }
                )
                + "\n"
            )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].snooze_until is None
        assert loaded[0].muted is True


class TestMarkManySnoozed:
    """Tests for ``mark_many_snoozed()``."""

    def test_round_trip_shared_deadline_with_missing_and_duplicate_ids(
        self, temp_notifications_dir: Path
    ) -> None:
        n1 = make_notification()
        n2 = make_notification()
        n3 = make_notification()
        for n in (n1, n2, n3):
            append_notification(n)
        deadline = datetime.now(get_timezone()) + timedelta(minutes=15)

        assert mark_many_snoozed([n1.id, "missing", n2.id, n1.id], deadline) == 2
        loaded = load_notifications()
        by_id = {n.id: n for n in loaded}
        assert by_id[n1.id].muted is True
        assert by_id[n2.id].muted is True
        assert by_id[n1.id].snooze_until == deadline.isoformat()
        assert by_id[n2.id].snooze_until == deadline.isoformat()
        assert by_id[n3.id].snooze_until is None

    def test_empty_input_skips_rust_call(self, temp_notifications_dir: Path) -> None:
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update"
        ) as mock_update:
            assert mark_many_snoozed([], datetime.now(get_timezone())) == 0
        mock_update.assert_not_called()

    def test_routes_through_one_rust_update(self, temp_notifications_dir: Path) -> None:
        n1 = make_notification()
        n2 = make_notification()
        append_notification(n1)
        append_notification(n2)
        deadline = datetime.now(get_timezone()) + timedelta(minutes=30)

        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=__import__(
                "sase.notifications.store",
                fromlist=["_rust_apply_notification_state_update"],
            )._rust_apply_notification_state_update,
        ) as mock_update:
            assert mark_many_snoozed([n1.id, n2.id], deadline) == 2

        assert mock_update.call_count == 1
        update = mock_update.call_args.args[1]
        assert update.kind == "mark_many_snoozed"
        assert update.ids == (n1.id, n2.id)
        assert update.until == deadline.isoformat()


class TestExpireDueSnoozes:
    """Tests for ``expire_due_snoozes()``."""

    def test_flips_ready_rows(self, temp_notifications_dir: Path) -> None:
        ready = make_notification()
        append_notification(ready)
        past = datetime.now(get_timezone()) - timedelta(seconds=1)
        mark_snoozed(ready.id, past)

        notifications = load_notifications()
        expired = expire_due_snoozes(notifications)

        assert len(expired) == 1
        assert expired[0].id == ready.id
        assert notifications[0].muted is False
        assert notifications[0].snooze_until is None
        reloaded = load_notifications()
        assert reloaded[0].muted is False
        assert reloaded[0].snooze_until is None

    def test_leaves_not_ready_rows(self, temp_notifications_dir: Path) -> None:
        not_ready = make_notification()
        append_notification(not_ready)
        future = datetime.now(get_timezone()) + timedelta(hours=1)
        mark_snoozed(not_ready.id, future)

        notifications = load_notifications()
        expired = expire_due_snoozes(notifications)

        assert expired == []
        assert notifications[0].muted is True
        assert notifications[0].snooze_until == future.isoformat()
        reloaded = load_notifications()
        assert reloaded[0].muted is True
        assert reloaded[0].snooze_until == future.isoformat()

    def test_returns_only_flipped_rows(self, temp_notifications_dir: Path) -> None:
        ready = make_notification()
        not_ready = make_notification()
        unsnoozed = make_notification()
        for n in (ready, not_ready, unsnoozed):
            append_notification(n)
        mark_snoozed(ready.id, datetime.now(get_timezone()) - timedelta(minutes=1))
        mark_snoozed(not_ready.id, datetime.now(get_timezone()) + timedelta(hours=1))

        notifications = load_notifications()
        expired = expire_due_snoozes(notifications)

        assert {n.id for n in expired} == {ready.id}

    def test_single_rewrite_for_batch(self, temp_notifications_dir: Path) -> None:
        n1 = make_notification()
        n2 = make_notification()
        append_notification(n1)
        append_notification(n2)
        past = datetime.now(get_timezone()) - timedelta(minutes=1)
        mark_snoozed(n1.id, past)
        mark_snoozed(n2.id, past)

        notifications = load_notifications()
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=__import__(
                "sase.notifications.store",
                fromlist=["_rust_apply_notification_state_update"],
            )._rust_apply_notification_state_update,
        ) as mock_update:
            expired = expire_due_snoozes(notifications)

        assert len(expired) == 2
        assert mock_update.call_count == 1
        assert mock_update.call_args.args[1].kind == "expire_snoozes"
        assert mock_update.call_args.kwargs == {"include_notifications": True}

    def test_empty_when_nothing_snoozed(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        notifications = load_notifications()
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update"
        ) as mock_update:
            expired = expire_due_snoozes(notifications)
        assert expired == []
        mock_update.assert_not_called()
