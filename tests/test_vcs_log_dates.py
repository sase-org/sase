"""Tests for ``sase vcs log`` date-bound parsing."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sase.core.time import get_timezone
from sase.vcs_log.dates import VcsLogDateError, parse_time_bound


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_parse_relative_offsets_against_configured_timezone() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)

    assert parse_time_bound("36h", now=now) == _epoch(now - timedelta(hours=36))
    assert parse_time_bound("2d", now=now) == _epoch(now - timedelta(days=2))
    assert parse_time_bound("3w", now=now) == _epoch(now - timedelta(weeks=3))


def test_parse_keywords_to_local_midnight() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)

    assert parse_time_bound("today", now=now) == _epoch(datetime(2026, 7, 8, tzinfo=tz))
    assert parse_time_bound("yesterday", now=now) == _epoch(
        datetime(2026, 7, 7, tzinfo=tz)
    )


def test_parse_iso_date_and_minute_datetime() -> None:
    tz = get_timezone()

    assert parse_time_bound("2026-07-08") == _epoch(datetime(2026, 7, 8, tzinfo=tz))
    assert parse_time_bound("2026-07-08T14:25") == _epoch(
        datetime(2026, 7, 8, 14, 25, tzinfo=tz)
    )


@pytest.mark.parametrize("value", ["", "last week", "2026-07", "2026-07-08T14"])
def test_parse_rejects_unsupported_forms(value: str) -> None:
    with pytest.raises(VcsLogDateError) as excinfo:
        parse_time_bound(value)

    assert "Accepted DATE forms" in str(excinfo.value)
