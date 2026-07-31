"""Snapshot tests for format_absolute_time."""

from datetime import datetime, timedelta, timezone, UTC

from inline_snapshot import snapshot

from sase.notifications.models import format_absolute_time


class TestFormatAbsoluteTime:
    """Tests for format_absolute_time using an injected 'now' for determinism."""

    def test_same_day(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 13, 18, 42, tzinfo=get_timezone())
        ts = datetime(2025, 6, 15, 8, 3, 9, tzinfo=get_timezone())
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot(
            "today 08:03:09"
        )

    def test_previous_day(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 9, 0, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 14, 21, 4, 0, tzinfo=get_timezone())
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot(
            "yesterday 21:04"
        )

    def test_earlier_this_year(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 9, 0, 0, tzinfo=get_timezone())
        ts = datetime(2025, 1, 12, 9, 31, 0, tzinfo=get_timezone())
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot("Jan 12 09:31")

    def test_previous_year(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 9, 0, 0, tzinfo=get_timezone())
        ts = datetime(2024, 7, 12, 9, 31, 0, tzinfo=get_timezone())
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot(
            "Jul 12 '24 09:31"
        )

    def test_day_boundary_is_calendar_based(self) -> None:
        """A 30-minute-old timestamp that crosses midnight tiers as yesterday."""
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 0, 20, 0, tzinfo=get_timezone())
        ts = datetime(2025, 6, 14, 23, 50, 0, tzinfo=get_timezone())
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot(
            "yesterday 23:50"
        )

    def test_naive_timestamp_uses_configured_timezone(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 13, 18, 42, tzinfo=get_timezone())
        ts_naive = datetime(2025, 6, 15, 8, 3, 9)  # No tzinfo
        assert format_absolute_time(ts_naive.isoformat(), now=now) == snapshot(
            "today 08:03:09"
        )

    def test_aware_timestamp_converted_from_other_offset(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 13, 18, 42, tzinfo=get_timezone())
        # 12:03:09 UTC == 08:03:09 in America/New_York (UTC-4 in June).
        ts_utc = datetime(2025, 6, 15, 12, 3, 9, tzinfo=UTC)
        assert format_absolute_time(ts_utc.isoformat(), now=now) == snapshot(
            "today 08:03:09"
        )

    def test_invalid_timestamp(self) -> None:
        assert format_absolute_time("not-a-date") == snapshot("not-a-date")

    def test_future_timestamp_never_says_today(self) -> None:
        from sase.core.time import get_timezone

        now = datetime(2025, 6, 15, 9, 0, 0, tzinfo=get_timezone())
        ts = now + timedelta(days=2)
        assert format_absolute_time(ts.isoformat(), now=now) == snapshot("Jun 17 09:00")
