from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sase.stats.ranges import (
    DEFAULT_PRESET,
    PRESETS,
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
    assert [(preset.key, preset.label) for preset in PRESETS] == [
        ("today", "Today"),
        ("24h", "Last 24 hours"),
        ("7d", "Last 7 days"),
        ("30d", "Last 30 days"),
        ("90d", "Last 90 days"),
        ("all", "All time"),
    ]


@pytest.mark.parametrize(
    ("key", "seconds", "display_label"),
    [
        ("24h", 86_400, "Last 24 hours"),
        ("7d", 604_800, "Last 7 days"),
        ("30d", 2_592_000, "Last 30 days"),
        ("90d", 7_776_000, "Last 90 days"),
    ],
)
def test_elapsed_time_presets_have_exact_lengths(
    key: str,
    seconds: int,
    display_label: str,
) -> None:
    result = resolve_preset(key, now=_NOW)  # type: ignore[arg-type]

    assert result.end_ts - result.start_ts == seconds
    assert result.display_label == display_label
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
    assert result.display_label == "Today"


def test_all_starts_at_unix_epoch() -> None:
    result = resolve_preset("all", now=_NOW)

    assert result.start_ts == 0
    assert result.end_ts == int(_NOW.timestamp())
    assert result.display_label == "All time"
    assert result.label == (
        "through 2026-07-18 14:30 EDT · start bounded by retained data"
    )
    assert "1969" not in result.label
    assert "1970" not in result.label


@pytest.mark.parametrize(
    ("value", "seconds", "display_label"),
    [
        ("1h", 3_600, "Last 1 hour"),
        ("3h", 10_800, "Last 3 hours"),
        ("1d", 86_400, "Last 1 day"),
        ("2d", 172_800, "Last 2 days"),
        ("1w", 604_800, "Last 1 week"),
        ("4w", 2_419_200, "Last 4 weeks"),
    ],
)
def test_relative_custom_ranges(
    value: str,
    seconds: int,
    display_label: str,
) -> None:
    result = parse_custom_range(f"  {value}  ", now=_NOW)

    assert result.end_ts - result.start_ts == seconds
    assert result.label.endswith("2026-07-18 14:30 EDT")
    assert result.display_label == display_label


def test_calendar_month_includes_whole_month_across_dst() -> None:
    result = parse_custom_range("2026-03", now=_NOW)

    assert datetime.fromtimestamp(result.start_ts, _EASTERN) == datetime(
        2026, 3, 1, tzinfo=_EASTERN
    )
    assert datetime.fromtimestamp(result.end_ts, _EASTERN) == datetime(
        2026, 4, 1, tzinfo=_EASTERN
    )
    assert result.label == "2026-03-01 00:00 EST – 2026-03-31 23:59 EDT"
    assert result.display_label == "March 2026"


def test_closed_date_range_includes_final_calendar_day() -> None:
    result = parse_custom_range("2026-07-01..2026-07-03", now=_NOW)

    assert datetime.fromtimestamp(result.start_ts, _EASTERN) == datetime(
        2026, 7, 1, tzinfo=_EASTERN
    )
    assert datetime.fromtimestamp(result.end_ts, _EASTERN) == datetime(
        2026, 7, 4, tzinfo=_EASTERN
    )
    assert result.label == "2026-07-01 00:00 EDT – 2026-07-03 23:59 EDT"
    assert result.display_label == "Jul 1–3, 2026"


@pytest.mark.parametrize(
    ("value", "display_label"),
    [
        ("2026-07-01..2026-07-01", "Jul 1, 2026"),
        ("2026-06-30..2026-07-02", "Jun 30–Jul 2, 2026"),
        ("2025-12-31..2026-01-02", "Dec 31, 2025–Jan 2, 2026"),
    ],
)
def test_closed_date_range_labels_are_compact_and_unambiguous(
    value: str,
    display_label: str,
) -> None:
    result = parse_custom_range(value, now=_NOW)

    assert result.display_label == display_label


def test_open_date_range_ends_now() -> None:
    result = parse_custom_range("2026-07-01..", now=_NOW)

    assert result == StatsRange(
        int(datetime(2026, 7, 1, tzinfo=_EASTERN).timestamp()),
        int(_NOW.timestamp()),
        "2026-07-01 00:00 EDT – 2026-07-18 14:30 EDT",
        "Since Jul 1, 2026",
    )


def test_current_month_is_capped_at_now() -> None:
    result = parse_custom_range("2026-07", now=_NOW)

    assert result.end_ts == int(_NOW.timestamp())
    assert result.label.endswith("2026-07-18 14:30 EDT")
    assert result.display_label == "July 2026 to date"


def test_future_closed_end_uses_the_effective_capped_range() -> None:
    result = parse_custom_range("2026-07-01..2026-12-31", now=_NOW)

    assert result.end_ts == int(_NOW.timestamp())
    assert result.label == "2026-07-01 00:00 EDT – 2026-07-18 14:30 EDT"
    assert result.display_label == "Jul 1–18, 2026 to date"


def test_relative_absolute_label_preserves_dst_boundary() -> None:
    now = datetime(2026, 3, 8, 12, 0, tzinfo=_EASTERN)

    result = resolve_preset("24h", now=now)

    assert result.label == "2026-03-07 11:00 EST – 2026-03-08 12:00 EDT"
    assert result.display_label == "Last 24 hours"


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
