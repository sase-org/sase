"""Tests for the StartupStopwatch widget's formatting and freeze behavior."""

from __future__ import annotations

from sase.ace.tui.widgets.startup_stopwatch import format_elapsed


def test_format_elapsed_sub_second() -> None:
    assert format_elapsed(0.0) == "00.0"
    assert format_elapsed(0.1) == "00.1"


def test_format_elapsed_seconds_and_tenths() -> None:
    assert format_elapsed(3.4) == "03.4"
    assert format_elapsed(12.9) == "12.9"


def test_format_elapsed_boundary_99_9() -> None:
    """At exactly 99.9 seconds we stay in SS.T format."""
    assert format_elapsed(99.9) == "99.9"


def test_format_elapsed_switches_to_mm_ss_t_past_99_9() -> None:
    """Beyond 99.9 seconds we switch to MM:SS.T."""
    # 100.0s -> 01:40.0
    assert format_elapsed(100.0) == "01:40.0"
    # 102.7s -> 01:42.7
    assert format_elapsed(102.7) == "01:42.7"


def test_format_elapsed_clamps_negative() -> None:
    """A negative reading (clock skew) clamps to zero."""
    assert format_elapsed(-0.5) == "00.0"


def test_format_elapsed_truncates_tenths() -> None:
    """Tenths are truncated toward zero, not rounded."""
    # 3.49 -> 03.4 (not 03.5)
    assert format_elapsed(3.49) == "03.4"


def test_format_elapsed_large_minutes() -> None:
    """Readings past 60 minutes still render as MM:SS.T."""
    # 3661.2 seconds -> 61:01.2 (we do not collapse into hours)
    assert format_elapsed(3661.2) == "61:01.2"
