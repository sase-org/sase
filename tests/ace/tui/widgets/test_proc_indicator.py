"""Unit tests for the top-bar proc and monitor gear chips."""

from __future__ import annotations

from sase.ace.tui.widgets.proc_indicator import MonitorIndicator, ProcIndicator


def test_proc_indicator_renders_blue_gear_chip_and_hides_at_zero() -> None:
    assert ProcIndicator._build_content(2).plain == " ⚙ 2 "
    assert ProcIndicator._build_content(2).style == "bold #1a1a1a on #48CAE4"
    assert ProcIndicator._build_content(0).plain == ""


def test_monitor_indicator_renders_amber_gear_chip_and_hides_at_zero() -> None:
    assert MonitorIndicator._build_content(1).plain == " ⚙ 1 "
    assert MonitorIndicator._build_content(1).style == "bold #1a1a1a on #FFAF5F"
    assert MonitorIndicator._build_content(0).plain == ""
