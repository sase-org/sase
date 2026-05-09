from pathlib import Path
from unittest.mock import patch

from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_all_read,
    mark_dismissed,
    mark_many_dismissed,
    mark_read,
)

from .helpers import make_notification


class TestMarkRead:
    """Tests for mark_read()."""

    def test_mark_existing(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_read(n.id) is True
        loaded = load_notifications()
        assert loaded[0].read is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_read("nonexistent") is False
        loaded = load_notifications()
        assert loaded[0].read is False

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = make_notification()
        append_notification(n)
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            assert mark_read(n.id) is True

        mock_update.assert_called_once()
        assert mock_update.call_args.args[1].kind == "mark_read"


class TestMarkDismissed:
    """Tests for mark_dismissed()."""

    def test_mark_existing(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_dismissed(n.id) is True
        loaded = load_notifications(include_dismissed=True)
        assert loaded[0].dismissed is True

    def test_nonexistent_id(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        assert mark_dismissed("nonexistent") is False
        loaded = load_notifications()
        assert loaded[0].dismissed is False


class TestMarkManyDismissed:
    """Tests for mark_many_dismissed()."""

    def test_marks_many_and_returns_matched_count(
        self, temp_notifications_dir: Path
    ) -> None:
        n1 = make_notification(id="n1")
        n2 = make_notification(id="n2")
        n3 = make_notification(id="n3")
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

        n = make_notification(id="n1")
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


class TestMarkAllRead:
    """Tests for mark_all_read()."""

    def test_skips_already_read(self, temp_notifications_dir: Path) -> None:
        n1 = make_notification(read=True)
        n2 = make_notification()
        append_notification(n1)
        append_notification(n2)
        count = mark_all_read()
        assert count == 1

    def test_empty_store(self, temp_notifications_dir: Path) -> None:
        count = mark_all_read()
        assert count == 0

    def test_uses_metadata_only_update(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = make_notification()
        append_notification(n)
        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            count = mark_all_read()

        assert count == 1
        mock_update.assert_called_once()
        assert mock_update.call_args.args[1].kind == "mark_all_read"
        assert mock_update.call_args.kwargs == {"include_notifications": False}
