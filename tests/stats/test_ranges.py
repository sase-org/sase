from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sase.stats.ranges import (
    DEFAULT_PRESET,
    PRESET_ORDER,
    StatsRange,
    bucket_seconds_for,
    parse_custom_range,
    resolve_preset,
)

_EASTERN = ZoneInfo("America/New_York")
_NOW = datetime(2026, 7, 18, 14, 30, tzinfo=_EASTERN)


def test_preset_order_and_default_match_product_design() -> None:
    assert PRESET_ORDER == ("today", "24h", "7d", "30d", "90d", "all")
    assert DEFAULT_PRESET == "7d"


@pytest.mark.parametrize(
    ("key", "seconds"),
    [("24h", 86_400), ("7d", 604_800), ("30d", 2_592_000), ("90d", 7_776_000)],
)
def test_elapsed_time_presets_have_exact_lengths(key: str, seconds: int) -> None:
    result = resolve_preset(key, now=_NOW)  # type: ignore[arg-type]

    assert result.end_ts - result.start_ts == seconds
    assert result.label == (
        f"{datetime.fromtimestamp(result.start_ts, _EASTERN):%Y-%m-%d %H:%M %Z} – "
        "2026-07-18 14:30 EDT"
    )


def test_today_uses_configured_timezone_midnight() -> None:
    result = resolve_preset("today", now=_NOW)

    assert datetime.fromtimestamp(result.start_ts, _EASTERN) == datetime(
        2026, 7, 18, tzinfo=_EASTERN
    )
    assert result.label == "2026-07-18 00:00 EDT – 2026-07-18 14:30 EDT"


def test_all_starts_at_unix_epoch() -> None:
    result = resolve_preset("all", now=_NOW)

    assert result.start_ts == 0
    assert result.end_ts == int(_NOW.timestamp())


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("3h", 10_800), ("2d", 172_800), ("4w", 2_419_200)],
)
def test_relative_custom_ranges(value: str, seconds: int) -> None:
    result = parse_custom_range(f"  {value}  ", now=_NOW)

    assert result.end_ts - result.start_ts == seconds
    assert result.label.endswith("2026-07-18 14:30 EDT")


def test_calendar_month_includes_whole_month_across_dst() -> None:
    result = parse_custom_range("2026-03", now=_NOW)

    assert datetime.fromtimestamp(result.start_ts, _EASTERN) == datetime(
        2026, 3, 1, tzinfo=_EASTERN
    )
    assert datetime.fromtimestamp(result.end_ts, _EASTERN) == datetime(
        2026, 4, 1, tzinfo=_EASTERN
    )
    assert result.label == "2026-03-01 00:00 EST – 2026-03-31 23:59 EDT"


def test_closed_date_range_includes_final_calendar_day() -> None:
    result = parse_custom_range("2026-07-01..2026-07-03", now=_NOW)

    assert datetime.fromtimestamp(result.start_ts, _EASTERN) == datetime(
        2026, 7, 1, tzinfo=_EASTERN
    )
    assert datetime.fromtimestamp(result.end_ts, _EASTERN) == datetime(
        2026, 7, 4, tzinfo=_EASTERN
    )
    assert result.label == "2026-07-01 00:00 EDT – 2026-07-03 23:59 EDT"


def test_open_date_range_ends_now() -> None:
    result = parse_custom_range("2026-07-01..", now=_NOW)

    assert result == StatsRange(
        int(datetime(2026, 7, 1, tzinfo=_EASTERN).timestamp()),
        int(_NOW.timestamp()),
        "2026-07-01 00:00 EDT – 2026-07-18 14:30 EDT",
    )


def test_current_month_is_capped_at_now() -> None:
    result = parse_custom_range("2026-07", now=_NOW)

    assert result.end_ts == int(_NOW.timestamp())
    assert result.label.endswith("2026-07-18 14:30 EDT")


def test_naive_now_is_interpreted_in_configured_timezone() -> None:
    result = parse_custom_range("1h", now=datetime(2026, 7, 18, 14, 30))

    assert result.end_ts == int(_NOW.timestamp())


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0h",
        "-1d",
        "7m",
        "2026-13",
        "2026-07-01",
        "..2026-07-01",
        "2026-07-03..2026-07-01",
        "2026-07-01..2026-07-02..",
        "2027-01..",
    ],
)
def test_invalid_custom_ranges_raise(value: str) -> None:
    with pytest.raises(ValueError):
        parse_custom_range(value, now=_NOW)


def test_bucket_size_switches_after_48_hours() -> None:
    assert bucket_seconds_for(100, 100 + 48 * 3_600) == 3_600
    assert bucket_seconds_for(100, 101 + 48 * 3_600) == 86_400
