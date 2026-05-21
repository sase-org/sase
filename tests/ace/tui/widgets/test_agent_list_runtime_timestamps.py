"""Tests for runtime timestamp formatting."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_time import _format_finish_timestamp


def test__format_finish_timestamp_same_day() -> None:
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("", "20:17:03")


def test__format_finish_timestamp_prior_day_same_year() -> None:
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Apr 24 ", "20:17")


def test__format_finish_timestamp_prior_year() -> None:
    stop = datetime(2025, 12, 31, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Dec 31 '25", "")
