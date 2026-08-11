"""Tests for ``sase stitch list`` date-bound parsing and resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sase.core.time import get_timezone
from sase.vcs_log.dates import (
    DATE_HELP,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_relative_bound_is_stable_hashable_and_reanchorable() -> None:
    tz = get_timezone()
    first_now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    later_now = first_now + timedelta(hours=4)

    first = parse_time_bound(" 36H ")
    reparsed = parse_time_bound("36h")

    assert first == reparsed
    assert hash(first) == hash(reparsed)
    assert first.resolve(now=first_now) == _epoch(first_now - timedelta(hours=36))
    assert first.resolve(now=later_now) == _epoch(later_now - timedelta(hours=36))


@pytest.mark.parametrize(
    ("value", "target_day"),
    (
        ("today", (2026, 7, 8)),
        ("yesterday", (2026, 7, 7)),
        ("2026-07-06", (2026, 7, 6)),
    ),
)
def test_day_granular_bounds_resolve_to_start_and_inclusive_end(
    value: str,
    target_day: tuple[int, int, int],
) -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    year, month, day = target_day
    start = datetime(year, month, day, tzinfo=tz)
    next_midnight = start + timedelta(days=1)
    bound = parse_time_bound(value)

    assert bound.is_day_granular is True
    assert bound.resolve(now=now, boundary="since") == _epoch(start)
    assert bound.resolve(now=now, boundary="until") == _epoch(next_midnight) - 1


@pytest.mark.parametrize(
    ("value", "expected_hours"),
    (("2026-03-08", 23), ("2026-11-01", 25)),
)
def test_day_bound_uses_adjacent_midnights_across_dst(
    value: str,
    expected_hours: int,
) -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    bound = parse_time_bound(value)

    since = bound.resolve(now=now, boundary="since")
    until = bound.resolve(now=now, boundary="until")

    assert until - since + 1 == expected_hours * 60 * 60


def test_relative_and_minute_bounds_are_exact_instants_for_either_direction() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    relative = parse_time_bound("2d")
    minute = parse_time_bound("2026-07-08T14:25")

    assert relative.is_day_granular is False
    assert relative.resolve(now=now, boundary="since") == relative.resolve(
        now=now,
        boundary="until",
    )
    expected_minute = _epoch(datetime(2026, 7, 8, 14, 25, tzinfo=tz))
    assert minute.resolve(now=now, boundary="since") == expected_minute
    assert minute.resolve(now=now, boundary="until") == expected_minute


def test_reference_time_normalizes_naive_and_aware_inputs() -> None:
    tz = get_timezone()
    naive = datetime(2026, 7, 8, 15, 30)
    aware_utc = datetime(2026, 7, 8, 19, 30, tzinfo=UTC)

    assert normalize_reference_time(naive) == naive.replace(tzinfo=tz)
    assert normalize_reference_time(aware_utc) == naive.replace(tzinfo=tz)


@pytest.mark.parametrize("value", ["", "last week", "2026-07", "2026-07-08T14"])
def test_parse_rejects_unsupported_forms(value: str) -> None:
    with pytest.raises(VcsLogDateError) as excinfo:
        parse_time_bound(value)

    assert "Accepted DATE forms" in str(excinfo.value)


def test_date_help_documents_inclusive_until_days() -> None:
    assert "until bounds include the full named day" in DATE_HELP
