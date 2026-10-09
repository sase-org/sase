"""Unit tests for the top-bar background-procs indicator chip."""

from __future__ import annotations

from sase.ace.tui.proc_gear_chips import PROC_GEAR_HUE, gear_chip
from sase.ace.tui.widgets.proc_indicator import ProcIndicator


def test_proc_indicator_renders_blue_chip_and_hides_at_zero() -> None:
    assert ProcIndicator._build_content(2) == gear_chip(2, PROC_GEAR_HUE)
    assert ProcIndicator._build_content(2).plain == " ⚙ 2 "
    assert ProcIndicator._build_content(2).style == "bold #1a1a1a on #48CAE4"
    assert ProcIndicator._build_content(0).plain == ""


def test_proc_indicator_group_label_is_bg() -> None:
    assert ProcIndicator.GROUP_LABEL == "bg"
    assert ProcIndicator.CLICK_ACTION == "open_tasks_panel"


def test_proc_indicator_tooltip_prefers_prebuilt_text() -> None:
    assert (
        ProcIndicator._build_tooltip(0, "")
        == "No TUI background procs\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(2, "")
        == "2 TUI background procs\nClick to open the Procs tab"
    )
    assert (
        ProcIndicator._build_tooltip(1, "")
        == "1 TUI background proc\nClick to open the Procs tab"
    )
    assert ProcIndicator._build_tooltip(0, "custom\nClick") == "custom\nClick"


def test_proc_indicator_set_model_noops_when_unchanged() -> None:
    indicator = ProcIndicator()
    indicator.set_model(2, "two\nClick to open the Procs tab")
    body = indicator._body.copy()  # noqa: SLF001
    tooltip = indicator.tooltip
    indicator.set_model(2, "two\nClick to open the Procs tab")
    assert indicator._body == body  # noqa: SLF001
    assert indicator.tooltip == tooltip
