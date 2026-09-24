"""Unit tests for the top-bar proc indicator chip."""

from __future__ import annotations

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE, gear_chip
from sase.ace.tui.widgets.proc_indicator import ProcIndicator


def test_proc_indicator_renders_blue_chip_and_hides_at_zero() -> None:
    assert ProcIndicator._build_content(2, 0) == gear_chip(2, PROC_GEAR_HUE)
    assert ProcIndicator._build_content(2, 0).plain == " ⚙ 2 "
    assert ProcIndicator._build_content(2, 0).style == "bold #1a1a1a on #48CAE4"
    assert ProcIndicator._build_content(0, 0).plain == ""


def test_proc_indicator_renders_orange_monitor_chip_alone() -> None:
    from rich.console import Console

    console = Console(color_system="truecolor", width=80)
    combined = ProcIndicator._build_content(0, 1)
    assert combined.plain == " ⚙ 1 "
    for offset in range(len(combined.plain)):
        style = combined.get_style_at_offset(console, offset)
        assert style.color is not None and style.bgcolor is not None
        assert (
            f"#{style.color.triplet.red:02X}{style.color.triplet.green:02X}"
            f"{style.color.triplet.blue:02X}" == "#1A1A1A"
        )
        assert (
            f"#{style.bgcolor.triplet.red:02X}{style.bgcolor.triplet.green:02X}"
            f"{style.bgcolor.triplet.blue:02X}" == "#FFAF5F"
        )


def test_proc_indicator_renders_both_chips_adjacent() -> None:
    from rich.console import Console

    console = Console(color_system="truecolor", width=80)
    combined = ProcIndicator._build_content(2, 1)
    assert combined.plain == " ⚙ 2  ⚙ 1 "
    expected = gear_chip(2, PROC_GEAR_HUE)
    expected.append_text(gear_chip(1, MONITOR_GEAR_HUE))
    assert combined == expected
    # Blue proc segment first, orange monitor segment second.
    first = combined.get_style_at_offset(console, 1)
    second = combined.get_style_at_offset(console, 6)
    assert str(first).lower() == "bold #1a1a1a on #48cae4"
    assert str(second).lower() == "bold #1a1a1a on #ffaf5f"


def test_proc_indicator_build_content_matches_concatenated_gear_chips() -> None:
    for procs, monitors in ((0, 0), (2, 0), (0, 1), (2, 1), (1, 3)):
        expected = gear_chip(procs, PROC_GEAR_HUE)
        expected.append_text(gear_chip(monitors, MONITOR_GEAR_HUE))
        assert ProcIndicator._build_content(procs, monitors) == expected


def test_proc_indicator_tooltip_names_counts_and_click() -> None:
    assert (
        ProcIndicator._build_tooltip(0, 0)
        == "No running procs\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(2, 0)
        == "2 running procs\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(1, 0)
        == "1 running proc\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(0, 1)
        == "1 running monitor\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(2, 1)
        == "2 running procs, 1 running monitor\nClick to open the Procs tab"
    )


def test_proc_indicator_set_counts_noops_when_unchanged() -> None:
    indicator = ProcIndicator()
    indicator.set_counts(2, 1)
    body = indicator._body.copy()  # noqa: SLF001
    tooltip = indicator.tooltip
    indicator.set_counts(2, 1)
    assert indicator._body == body  # noqa: SLF001
    assert indicator.tooltip == tooltip
