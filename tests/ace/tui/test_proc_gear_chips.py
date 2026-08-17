"""Unit tests for the shared blue/orange gear-chip builder."""

from __future__ import annotations

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE, gear_chip


def test_gear_chip_hides_at_zero_by_default() -> None:
    assert gear_chip(0, PROC_GEAR_HUE).plain == ""


def test_gear_chip_zero_state_renders_dim_unfilled_chip() -> None:
    chip = gear_chip(0, PROC_GEAR_HUE, hide_at_zero=False)
    assert chip.plain == " ⚙ 0 "
    assert chip.style == f"dim {PROC_GEAR_HUE}"


def test_gear_chip_nonzero_renders_filled_chip_regardless_of_hide_at_zero() -> None:
    hidden = gear_chip(3, MONITOR_GEAR_HUE)
    shown = gear_chip(3, MONITOR_GEAR_HUE, hide_at_zero=False)
    assert hidden.plain == shown.plain == " ⚙ 3 "
    assert hidden.style == shown.style == f"bold #1a1a1a on {MONITOR_GEAR_HUE}"


def test_gear_hues_match_the_canonical_top_bar_lanes() -> None:
    assert PROC_GEAR_HUE == "#48CAE4"
    assert MONITOR_GEAR_HUE == "#FFAF5F"
