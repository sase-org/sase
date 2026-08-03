"""Core regression tests for configured-timezone display consistency.

The ``tz_divergence`` fixture (see ``tests/conftest.py``) forces configured tz
(``America/New_York``) != system tz (``UTC``) so incorrect clock conversions
remain visible.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sase.core.time import format_local, parse_local


# --- parse_local / format_local: aware-UTC input --------------------------


def test_parse_local_converts_aware_utc_z_suffix(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T10:24:49Z")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_converts_aware_utc_offset_suffix(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T10:24:49+00:00")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_converts_non_utc_offset(tz_divergence: None) -> None:
    # 2026-07-03T14:24:49+04:00 is the same instant as 10:24:49 UTC.
    parsed = parse_local("2026-07-03T14:24:49+04:00")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: naive input is already configured-tz wall time ---------


def test_parse_local_naive_iso_is_unchanged_wall_clock(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T06:24:49")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_naive_datetime_is_unchanged_wall_clock(
    tz_divergence: None,
) -> None:
    parsed = parse_local(datetime(2026, 7, 3, 6, 24, 49))
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_aware_datetime_converts(tz_divergence: None) -> None:
    parsed = parse_local(datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC))
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: epoch input ---------------------------------------------


def test_parse_local_epoch_int_lands_on_configured_wall_clock(
    tz_divergence: None,
) -> None:
    epoch = int(datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp())
    parsed = parse_local(epoch)
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_epoch_float_lands_on_configured_wall_clock(
    tz_divergence: None,
) -> None:
    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()
    parsed = parse_local(epoch)
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: unparseable / empty inputs ------------------------------


def test_parse_local_none_returns_none(tz_divergence: None) -> None:
    assert parse_local(None) is None


def test_parse_local_empty_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("") is None


def test_parse_local_whitespace_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("   ") is None


def test_parse_local_garbage_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("not-a-timestamp") is None


# --- format_local ----------------------------------------------------------


def test_format_local_formats_in_configured_tz(tz_divergence: None) -> None:
    assert format_local("2026-07-03T10:24:49Z") == "2026-07-03 06:24:49"


def test_format_local_honors_custom_fmt(tz_divergence: None) -> None:
    assert format_local("2026-07-03T10:24:49Z", "%H:%M") == "06:24"


def test_format_local_honors_custom_default(tz_divergence: None) -> None:
    assert format_local(None, default="N/A") == "N/A"
    assert format_local("garbage", default="N/A") == "N/A"


def test_format_local_default_placeholder_for_unparseable(tz_divergence: None) -> None:
    assert format_local(None) == "—"
