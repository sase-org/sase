"""Tests for the notification data model and JSONL storage layer."""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    NotificationUpdateOutcomeWire,
)
from sase.core.time import get_timezone

import pytest

from sase.notifications.models import Notification
from sase.notifications.store import (
    append_notification,
    dismiss_notifications_matching_agents,
    expire_due_snoozes,
    load_notifications,
    mark_all_read,
    mark_dismissed,
    mark_many_dismissed,
    mark_muted,
    mark_read,
    mark_snoozed,
    rewrite_notifications,
)


def _make_notification(
    *,
    id: str | None = None,
    sender: str = "test-sender",
    notes: list[str] | None = None,
    files: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
) -> Notification:
    """Factory for creating test notifications with sensible defaults."""
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
    )


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch NOTIFICATIONS_DIR and NOTIFICATIONS_FILE to use tmp_path."""
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


# =========================================================================
# TestNotificationModel
# =========================================================================


class TestNotificationModel:
    """Tests for the Notification dataclass."""

    def test_required_fields(self) -> None:
        n = Notification(id="abc", timestamp="2025-01-01T00:00:00", sender="test")
        assert n.id == "abc"
        assert n.sender == "test"

    def test_default_values(self) -> None:
        n = Notification(id="abc", timestamp="2025-01-01T00:00:00", sender="test")
        assert n.notes == []
        assert n.files == []
        assert n.action is None
        assert n.action_data == {}
        assert n.read is False
        assert n.dismissed is False

    def test_all_fields(self) -> None:
        n = Notification(
            id="abc",
            timestamp="2025-01-01T00:00:00",
            sender="crs",
            notes=["line1", "line2"],
            files=["/tmp/a.py"],
            action="HITL",
            action_data={"key": "value"},
            read=True,
            dismissed=True,
        )
        assert n.notes == ["line1", "line2"]
        assert n.action == "HITL"
        assert n.action_data == {"key": "value"}
        assert n.read is True
        assert n.dismissed is True

    def test_silent_field(self) -> None:
        n = Notification(
            id="abc",
            timestamp="2025-01-01T00:00:00",
            sender="crs",
            silent=True,
        )
        assert n.silent is True


# =========================================================================
# TestAppendNotification
# =========================================================================


class TestAppendNotification:
    """Tests for append_notification()."""

    def test_silent_notification_round_trip(self, temp_notifications_dir: Path) -> None:
        """Silent notifications are stored and loaded back with silent=True."""
        n = _make_notification(silent=True)
        append_notification(n)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is True

    def test_non_silent_notification_round_trip(
        self, temp_notifications_dir: Path
    ) -> None:
        """Non-silent notifications default to silent=False after round-trip."""
        n = _make_notification()
        append_notification(n)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is False

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = _make_notification()
        with patch(
            "sase.notifications.store._rust_append_notification",
            wraps=store._rust_append_notification,
        ) as mock_append:
            append_notification(n)

        mock_append.assert_called_once()


# =========================================================================
# TestLoadNotifications
# =========================================================================


class TestLoadNotifications:
    """Tests for load_notifications()."""

    def test_skips_invalid_json(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        # Append invalid line directly
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        with open(jsonl, "a") as f:
            f.write("NOT VALID JSON\n")
        loaded = load_notifications()
        assert len(loaded) == 1

    def test_skips_missing_fields(self, temp_notifications_dir: Path) -> None:
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w") as f:
            f.write(json.dumps({"id": "abc"}) + "\n")  # missing sender, timestamp
        loaded = load_notifications()
        assert len(loaded) == 0

    def test_skips_blank_lines(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        with open(jsonl, "a") as f:
            f.write("\n\n")
        loaded = load_notifications()
        assert len(loaded) == 1


# =========================================================================
# TestMarkRead
# =========================================================================


class TestMarkRead:
    """Tests for mark_read()."""

    def test_mark_existing(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_read(n.id) is True
        loaded = load_notifications()
        assert loaded[0].read is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_read("nonexistent") is False
        loaded = load_notifications()
        assert loaded[0].read is False

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = _make_notification()
        append_notification(n)
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            assert mark_read(n.id) is True

        mock_update.assert_called_once()
        assert mock_update.call_args.args[1].kind == "mark_read"


# =========================================================================
# TestMarkDismissed
# =========================================================================


class TestMarkDismissed:
    """Tests for mark_dismissed()."""

    def test_mark_existing(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_dismissed(n.id) is True
        loaded = load_notifications(include_dismissed=True)
        assert loaded[0].dismissed is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_dismissed("nonexistent") is False
        loaded = load_notifications()
        assert loaded[0].dismissed is False


class TestMarkManyDismissed:
    """Tests for mark_many_dismissed()."""

    def test_marks_many_and_returns_matched_count(
        self, temp_notifications_dir: Path
    ) -> None:
        n1 = _make_notification(id="n1")
        n2 = _make_notification(id="n2")
        n3 = _make_notification(id="n3")
        for notification in (n1, n2, n3):
            append_notification(notification)

        count = mark_many_dismissed(["n1", "n3", "missing"])

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 2
        assert by_id["n1"].dismissed is True
        assert by_id["n2"].dismissed is False
        assert by_id["n3"].dismissed is True

    def test_empty_ids_skip_store_update(self, temp_notifications_dir: Path) -> None:
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update"
        ) as mock_update:
            assert mark_many_dismissed([]) == 0

        mock_update.assert_not_called()

    def test_routes_through_bulk_rust_update(
        self, temp_notifications_dir: Path
    ) -> None:
        import sase.notifications.store as store

        n = _make_notification(id="n1")
        append_notification(n)
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            assert mark_many_dismissed(["n1"]) == 1

        mock_update.assert_called_once()
        update = mock_update.call_args.args[1]
        assert update.kind == "mark_many_dismissed"
        assert update.ids == ("n1",)


# =========================================================================
# TestMarkAllRead
# =========================================================================


class TestMarkMuted:
    """Tests for mark_muted()."""

    def test_mute_existing(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_muted(n.id, True) is True
        loaded = load_notifications()
        assert loaded[0].muted is True

    def test_unmute_existing(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        mark_muted(n.id, True)
        assert mark_muted(n.id, False) is True
        loaded = load_notifications()
        assert loaded[0].muted is False

    def test_default_value_mutes(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        assert mark_muted(n.id) is True
        loaded = load_notifications()
        assert loaded[0].muted is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
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
        n = _make_notification()
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


class TestMarkSnoozed:
    """Tests for ``mark_snoozed()``."""

    def test_round_trip(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        deadline = datetime.now(get_timezone()) + timedelta(minutes=15)
        assert mark_snoozed(n.id, deadline) is True
        loaded = load_notifications()
        assert loaded[0].muted is True
        assert loaded[0].snooze_until == deadline.isoformat()

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
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


class TestExpireDueSnoozes:
    """Tests for ``expire_due_snoozes()``."""

    def test_flips_ready_rows(self, temp_notifications_dir: Path) -> None:
        ready = _make_notification()
        append_notification(ready)
        past = datetime.now(get_timezone()) - timedelta(seconds=1)
        mark_snoozed(ready.id, past)

        notifications = load_notifications()
        expired = expire_due_snoozes(notifications)

        assert len(expired) == 1
        assert expired[0].id == ready.id
        # In-memory mutation
        assert notifications[0].muted is False
        assert notifications[0].snooze_until is None
        # Persisted
        reloaded = load_notifications()
        assert reloaded[0].muted is False
        assert reloaded[0].snooze_until is None

    def test_leaves_not_ready_rows(self, temp_notifications_dir: Path) -> None:
        not_ready = _make_notification()
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
        ready = _make_notification()
        not_ready = _make_notification()
        unsnoozed = _make_notification()
        for n in (ready, not_ready, unsnoozed):
            append_notification(n)
        mark_snoozed(ready.id, datetime.now(get_timezone()) - timedelta(minutes=1))
        mark_snoozed(not_ready.id, datetime.now(get_timezone()) + timedelta(hours=1))

        notifications = load_notifications()
        expired = expire_due_snoozes(notifications)

        assert {n.id for n in expired} == {ready.id}

    def test_single_rewrite_for_batch(self, temp_notifications_dir: Path) -> None:
        n1 = _make_notification()
        n2 = _make_notification()
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

    def test_empty_when_nothing_snoozed(self, temp_notifications_dir: Path) -> None:
        n = _make_notification()
        append_notification(n)
        notifications = load_notifications()
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update"
        ) as mock_update:
            expired = expire_due_snoozes(notifications)
        assert expired == []
        mock_update.assert_not_called()


class TestMarkAllRead:
    """Tests for mark_all_read()."""

    def test_skips_already_read(self, temp_notifications_dir: Path) -> None:
        n1 = _make_notification(read=True)
        n2 = _make_notification()
        append_notification(n1)
        append_notification(n2)
        count = mark_all_read()
        assert count == 1

    def test_empty_store(self, temp_notifications_dir: Path) -> None:
        # No file exists yet — should not error
        count = mark_all_read()
        assert count == 0


class TestRewriteNotifications:
    """Tests for rewrite_notifications()."""

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = _make_notification()
        with patch(
            "sase.notifications.store._rust_rewrite_notifications",
            wraps=store._rust_rewrite_notifications,
        ) as mock_rewrite:
            rewrite_notifications([n])

        mock_rewrite.assert_called_once()
        assert load_notifications()[0].id == n.id


class TestRustBackedCache:
    """Tests for cache behavior around Rust-backed writes."""

    def test_rust_write_invalidates_cached_snapshot(
        self, temp_notifications_dir: Path
    ) -> None:
        import sase.notifications.store as store

        n = _make_notification()
        append_notification(n)
        outcome = NotificationUpdateOutcomeWire(
            schema_version=NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            matched_count=1,
            changed_count=1,
            rewritten=True,
        )

        with (
            patch(
                "sase.notifications.store._rust_read_notifications_snapshot",
                wraps=store._rust_read_notifications_snapshot,
            ) as mock_read,
            patch(
                "sase.notifications.store._rust_apply_notification_state_update",
                return_value=outcome,
            ),
        ):
            assert load_notifications()[0].id == n.id
            assert load_notifications()[0].id == n.id
            assert mock_read.call_count == 1

            assert mark_read(n.id) is True
            assert load_notifications()[0].id == n.id
            assert mock_read.call_count == 2


class TestDismissNotificationsMatchingAgents:
    """Tests for Rust-backed bulk agent notification dismissal."""

    def test_dismisses_matching_agent_notifications(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            _make_notification(
                id="jump",
                action="JumpToAgent",
                action_data={"cl_name": "cl", "raw_suffix": "20260430120000"},
            )
        )
        append_notification(
            _make_notification(
                id="other",
                action="JumpToAgent",
                action_data={"cl_name": "other", "raw_suffix": "20260430120000"},
            )
        )

        count = dismiss_notifications_matching_agents(
            [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["jump"].dismissed is True
        assert by_id["other"].dismissed is False


# =========================================================================
# TestNotifyWorkflowCompleteSilent
# =========================================================================


class TestNotifyWorkflowCompleteSilent:
    """Tests for notify_workflow_complete() with silent flag."""

    def test_silent_notification_created(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="fix-hook",
            cl_name="test-cl",
            success=True,
            notes=["Fix-hook completed for test-cl"],
            silent=True,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is True
        assert loaded[0].sender == "fix-hook"

    def test_non_silent_notification_default(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="run-agent",
            cl_name="test-cl",
            success=True,
            notes=["Agent completed"],
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is False


class TestNotifyMentorsComplete:
    """Tests for notify_mentors_complete()."""

    def test_emits_jump_to_mentor_review_action(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_mentors_complete

        notify_mentors_complete(
            cl_name="cl-1",
            project_file="/proj.gp",
            entry_id="2",
            mentor_summary="3/3 mentors finished (1 commented)",
            has_comments=True,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        n = loaded[0]
        assert n.action == "JumpToMentorReview"
        assert n.action_data == {
            "changespec_name": "cl-1",
            "project_file": "/proj.gp",
            "entry_id": "2",
        }
        assert n.sender == "mentors"
        assert n.files == ["/proj.gp"]
        assert any("cl-1" in note and "entry 2" in note for note in n.notes)
        assert "3/3 mentors finished (1 commented)" in n.notes

    def test_no_match_summary(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_mentors_complete

        notify_mentors_complete(
            cl_name="cl-1",
            project_file="/proj.gp",
            entry_id="1",
            mentor_summary="no mentor profiles matched",
            has_comments=False,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert "no mentor profiles matched" in loaded[0].notes
