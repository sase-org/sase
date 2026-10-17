"""Byte-stable Statistics render primitives used by the TUI and later CLI."""

from __future__ import annotations

import math

from sase.stats.render.primitives import (
    format_compact,
    format_count,
    format_duration,
    format_relative_age,
    percent,
    share_bar,
    stacked_bar,
)
from sase.telemetry.render import format_duration as telemetry_format_duration


def test_percent_matches_the_previous_statistics_mixin() -> None:
    assert percent(0.0) == "0.0%"
    assert percent(0.6) == "60.0%"
    assert percent(1.0) == "100.0%"
    assert percent(0.1234) == "12.3%"


def test_share_bar_matches_the_previous_statistics_mixin() -> None:
    bar = share_bar(1, 2, width=14)
    assert bar.plain == ("█" * 7) + ("░" * 7)
    assert bar.spans[0].style == "#FF87D7"
    assert bar.spans[1].style == "#444444"

    empty = share_bar(1, 0, width=8)
    assert empty.plain == "░" * 8
    full = share_bar(9, 3, width=6)
    assert full.plain == "█" * 6


def test_share_bar_ascii_fallback_uses_hash_and_dot() -> None:
    bar = share_bar(1, 4, width=8, ascii_fallback=True)
    assert bar.plain == "##......"


def test_stacked_bar_uses_largest_remainder_and_leaves_unused_width() -> None:
    bar = stacked_bar(((0.5, "red"), (0.25, "blue")), width=8)
    assert bar.plain == ("█" * 4) + ("▓" * 2) + ("░" * 2)
    assert [span.style for span in bar.spans] == ["red", "blue", "#444444"]

    thirds = stacked_bar(((1 / 3, "a"), (1 / 3, "b"), (1 / 3, "c")), width=10)
    assert thirds.plain == ("█" * 4) + ("▓" * 3) + ("▒" * 3)
    assert len(thirds.plain) == 10


def test_stacked_bar_ascii_fallback_and_empty_parts() -> None:
    bar = stacked_bar(((0.5, "red"), (0.5, "blue")), width=6, ascii_fallback=True)
    assert bar.plain == "###%%%"
    empty = stacked_bar((), width=4)
    assert empty.plain == "░░░░"


def test_format_count_uses_thousands_separators() -> None:
    assert format_count(0) == "0"
    assert format_count(1234) == "1,234"
    assert format_count(1_000_000) == "1,000,000"
    assert format_count(math.inf) == "—"
    assert format_count(math.nan) == "—"


def test_format_compact_uses_the_specified_magnitude_grammar() -> None:
    assert format_compact(0) == "0"
    assert format_compact(3.1e6) == "3.1M"
    assert format_compact(3_100_000) == "3.1M"
    assert format_compact(1500) == "1.5k"
    assert format_compact(math.inf) == "—"


def test_format_duration_wraps_the_telemetry_formatter() -> None:
    assert format_duration(0.125) == telemetry_format_duration(0.125) == "125ms"
    assert format_duration(65) == telemetry_format_duration(65) == "1m05s"


def test_format_relative_age_uses_friendly_buckets() -> None:
    assert format_relative_age(12) == "just now"
    assert format_relative_age(60) == "1 min ago"
    assert format_relative_age(4 * 60) == "4 min ago"
    assert format_relative_age(3 * 3600) == "3 h ago"
    assert format_relative_age(2 * 86400) == "2 d ago"
    assert format_relative_age(70 * 86400) == "2 mo ago"
    assert format_relative_age(800 * 86400) == "2 yr ago"
