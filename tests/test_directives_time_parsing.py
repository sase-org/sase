"""Tests for parse_duration and parse_absolute_time."""

from datetime import datetime, timedelta

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import parse_absolute_time, parse_duration


# --- parse_duration tests ---


def test_parse_duration_minutes() -> None:
    """'5m' parses to 300 seconds."""
    assert parse_duration("5m") == 300.0


def test_parse_duration_hours() -> None:
    """'1h' parses to 3600 seconds."""
    assert parse_duration("1h") == 3600.0


def test_parse_duration_seconds() -> None:
    """'90s' parses to 90 seconds."""
    assert parse_duration("90s") == 90.0


def test_parse_duration_hours_minutes() -> None:
    """'2h30m' parses to 9000 seconds."""
    assert parse_duration("2h30m") == 9000.0


def test_parse_duration_full() -> None:
    """'1h30m15s' parses to 5415 seconds."""
    assert parse_duration("1h30m15s") == 5415.0


def test_parse_duration_zero() -> None:
    """'0s' parses to 0."""
    assert parse_duration("0s") == 0.0


def test_parse_duration_all_zeros() -> None:
    """'0h0m0s' parses to 0."""
    assert parse_duration("0h0m0s") == 0.0


def test_parse_duration_invalid_unit() -> None:
    """'5x' is not a valid duration."""
    assert parse_duration("5x") is None


def test_parse_duration_wrong_order() -> None:
    """'5m3h' is not valid (units must be h > m > s)."""
    assert parse_duration("5m3h") is None


def test_parse_duration_duplicate_unit() -> None:
    """'5m5m' is not valid."""
    assert parse_duration("5m5m") is None


def test_parse_duration_agent_name() -> None:
    """Agent names (start with letter) return None."""
    assert parse_duration("abc") is None


def test_parse_duration_empty() -> None:
    """Empty string returns None."""
    assert parse_duration("") is None


# --- parse_absolute_time tests ---


def test_parse_absolute_time_hhmm_future() -> None:
    """HHMM in the future returns today's ISO string."""
    # Use 23:59 which is almost certainly in the future relative to test time
    # (unless tests run at exactly 23:59)
    tomorrow = datetime.now() + timedelta(days=1)
    result = parse_absolute_time(tomorrow.strftime("%H%M"))
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.hour == tomorrow.hour
    assert target.minute == tomorrow.minute


def test_parse_absolute_time_hhmm_past_wraps_to_tomorrow() -> None:
    """HHMM in the past wraps to tomorrow."""
    # Use 00:00 which is almost certainly in the past
    result = parse_absolute_time("0000")
    assert result is not None
    target = datetime.fromisoformat(result)
    # Should be tomorrow (since 00:00 today has passed)
    assert target.date() == (datetime.now() + timedelta(days=1)).date()


def test_parse_absolute_time_yymmdd_hhmm_future() -> None:
    """yymmdd/HHMM in the future returns correct ISO string."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    result = parse_absolute_time(f"{date_str}/1430")
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.year == future.year
    assert target.month == future.month
    assert target.day == future.day
    assert target.hour == 14
    assert target.minute == 30


def test_parse_absolute_time_yymmdd_hhmm_past_raises() -> None:
    """yymmdd/HHMM in the past raises DirectiveError."""
    past = datetime.now() - timedelta(days=30)
    date_str = past.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="in the past"):
        parse_absolute_time(f"{date_str}/0000")


def test_parse_absolute_time_invalid_hour() -> None:
    """Hour > 23 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        parse_absolute_time("2500")


def test_parse_absolute_time_invalid_minute() -> None:
    """Minute > 59 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="minutes 00-59"):
        parse_absolute_time("1261")


def test_parse_absolute_time_invalid_month() -> None:
    """Month > 12 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="month must be 01-12"):
        parse_absolute_time("261311/1430")


def test_parse_absolute_time_invalid_day() -> None:
    """Day > 31 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="day must be 01-31"):
        parse_absolute_time("260132/1430")


def test_parse_absolute_time_invalid_date_combo() -> None:
    """Feb 30 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="Invalid date/time"):
        parse_absolute_time("260230/1430")


def test_parse_absolute_time_no_match() -> None:
    """Non-matching strings return None."""
    assert parse_absolute_time("abc") is None
    assert parse_absolute_time("5m") is None
    assert parse_absolute_time("12345") is None
    assert parse_absolute_time("") is None


def test_parse_absolute_time_yymmdd_invalid_hour() -> None:
    """yymmdd/HHMM with invalid hour raises DirectiveError."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        parse_absolute_time(f"{date_str}/2500")
