"""Tests for the shared notifications timestamp sort key."""

from datetime import datetime

from sase.core.time import get_timezone
from sase.notifications import Notification
from sase.notifications.sort import timestamp_sort_key


def _notification(timestamp: str) -> Notification:
    return Notification(id="x", timestamp=timestamp, sender="test")


def test_tz_aware_timestamp_returns_parsed_datetime() -> None:
    key = timestamp_sort_key(_notification("2026-03-17T12:00:00-04:00"))
    assert key == datetime.fromisoformat("2026-03-17T12:00:00-04:00")
    assert key.tzinfo is not None


def test_tz_naive_timestamp_is_promoted_to_project_timezone() -> None:
    key = timestamp_sort_key(_notification("2026-03-17T12:00:00"))
    assert key.tzinfo is not None
    expected = datetime.fromisoformat("2026-03-17T12:00:00").replace(
        tzinfo=get_timezone()
    )
    assert key == expected


def test_malformed_timestamp_falls_back_to_floor() -> None:
    key = timestamp_sort_key(_notification("not-a-timestamp"))
    assert key == datetime.min.replace(tzinfo=get_timezone())
