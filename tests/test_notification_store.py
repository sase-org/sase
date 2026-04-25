"""Tests for the notification data model and JSONL storage layer."""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from sase.core.time import get_timezone

import pytest

from sase.notifications.models import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_all_read,
    mark_dismissed,
    mark_read,
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


# =========================================================================
# TestMarkAllRead
# =========================================================================


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
