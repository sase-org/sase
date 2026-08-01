"""Snapshot tests for notification data models."""

from datetime import datetime
from unittest.mock import patch

from inline_snapshot import snapshot

from sase.notifications.models import (
    Notification,
    format_relative_time,
    format_relative_until,
    notification_activity_at,
    notification_activity_cursor,
    normalize_notification_tags,
)


class TestNotificationDataclass:
    def test_defaults(self) -> None:
        n = Notification(id="abc", timestamp="2025-01-01T00:00:00", sender="crs")
        assert n.notes == snapshot([])
        assert n.files == snapshot([])
        assert n.tags == snapshot([])
        assert n.action is None
        assert n.action_data == snapshot({})
        assert n.read is False
        assert n.dismissed is False
        assert n.silent is False
        assert n.muted is False
        assert n.snooze_until is None
        assert n.resurfaced_at is None

    def test_activity_cursor_prefers_resurface_time_and_breaks_ties_by_id(
        self,
    ) -> None:
        original = Notification(
            id="a", timestamp="2025-01-01T00:00:00+00:00", sender="crs"
        )
        resurfaced = Notification(
            id="b",
            timestamp="2024-01-01T00:00:00+00:00",
            sender="crs",
            resurfaced_at="2025-02-01T00:00:00+00:00",
        )

        assert notification_activity_at(original) == original.timestamp
        assert notification_activity_cursor(resurfaced) == (
            "2025-02-01T00:00:00+00:00",
            "b",
        )

    def test_silent_flag(self) -> None:
        n = Notification(
            id="abc", timestamp="2025-01-01T00:00:00", sender="crs", silent=True
        )
        assert n.silent is True


class TestNormalizeNotificationTags:
    def test_none_returns_empty_list(self) -> None:
        assert normalize_notification_tags(None) == snapshot([])

    def test_trims_lowercases_drops_empty_and_dedupes(self) -> None:
        assert normalize_notification_tags(
            [" Done ", "", "done", "Review", " review "]
        ) == snapshot(["done", "review"])

    def test_single_string_is_one_tag(self) -> None:
        assert normalize_notification_tags(" Done ") == snapshot(["done"])


class TestFormatRelativeTime:
    """Tests for format_relative_time using a fixed 'now' via mocking."""

    def _make_iso(self, dt: datetime) -> str:
        return dt.isoformat()

    def test_seconds_ago(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 30, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 12, 0, 5, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(self._make_iso(ts)) == snapshot("25s ago")

    def test_minutes_ago(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 5, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(self._make_iso(ts)) == snapshot("5m ago")

    def test_hours_ago(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 15, 0, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(self._make_iso(ts)) == snapshot("3h ago")

    def test_days_ago(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 18, 12, 0, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(self._make_iso(ts)) == snapshot("3d ago")

    def test_future_timestamp(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 12, 5, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(self._make_iso(ts)) == snapshot("just now")

    def test_invalid_timestamp(self) -> None:
        assert format_relative_time("not-a-date") == snapshot("not-a-date")

    def test_naive_timestamp_gets_tz(self) -> None:
        """Naive timestamps (no tzinfo) should be treated as Eastern."""
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 2, 0, tzinfo=get_timezone())
        ts_naive = datetime(2025, 6, 15, 12, 0, 0)  # No tzinfo
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_time(ts_naive.isoformat()) == snapshot("2m ago")


class TestFormatRelativeUntil:
    """Tests for format_relative_until (forward-reading remaining time)."""

    def test_under_one_minute(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        target = datetime(2025, 6, 15, 12, 0, 30, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_until(target.isoformat()) == snapshot("< 1m")

    def test_minutes(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        target = datetime(2025, 6, 15, 12, 14, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_until(target.isoformat()) == snapshot("14m")

    def test_hours(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        target = datetime(2025, 6, 15, 14, 0, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_until(target.isoformat()) == snapshot("2h")

    def test_days(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        target = datetime(2025, 6, 16, 12, 0, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_until(target.isoformat()) == snapshot("1d")

    def test_past_due(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=get_timezone())
        target = datetime(2025, 6, 15, 11, 59, 0, tzinfo=get_timezone())
        with patch("sase.notifications.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert format_relative_until(target.isoformat()) == snapshot("expiring…")
