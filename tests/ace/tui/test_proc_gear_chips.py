"""Unit tests for the shared blue/orange/green gear-chip builders."""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.proc_gear_chips import (
    MONITOR_GEAR_HUE,
    PROC_GEAR_HUE,
    UPDATE_GEAR_HUE,
    UPDATE_GEAR_HUES,
    gear_chip,
    update_gear_chip,
)
from sase.ace.tui.widgets.update_accents import (
    UPDATES_ACCENT,
    UPDATE_FAILED_ACCENT,
    UPDATE_RESTART_ACCENT,
)


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


def test_update_gear_chip_renders_each_state_with_dark_ink() -> None:
    expected = {
        "updating": UPDATES_ACCENT,
        "restart_pending": UPDATE_RESTART_ACCENT,
        "failed": UPDATE_FAILED_ACCENT,
    }
    for state, hue in expected.items():
        chip = update_gear_chip(state)  # type: ignore[arg-type]
        assert chip.plain == " ⚙ "
        assert chip.style == f"bold #1a1a1a on {hue}"
        assert UPDATE_GEAR_HUES[state] == hue  # type: ignore[index]


def test_update_gear_chip_hides_when_inactive() -> None:
    assert update_gear_chip(None).plain == ""


def test_update_gear_hue_is_updates_accent() -> None:
    assert UPDATE_GEAR_HUE == UPDATES_ACCENT


def test_update_gear_states_share_cell_width() -> None:
    widths = {
        cell_len(update_gear_chip(state).plain)  # type: ignore[arg-type]
        for state in ("updating", "restart_pending", "failed")
    }
    assert widths == {cell_len(" ⚙ ")}
