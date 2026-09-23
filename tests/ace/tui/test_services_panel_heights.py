"""Shared stacked-panel height allocation and Services sidebar width."""

from __future__ import annotations

from sase.ace.tui._app_layout import (
    MAX_BGCMD_LIST_WIDTH,
    MIN_BGCMD_LIST_WIDTH,
    services_sidebar_width,
)
from sase.ace.tui.util.panel_heights import allocate_panel_heights


def _scalars(heights) -> list[tuple[float, str]]:
    assert heights is not None
    return [(h.value, h.unit) for h in heights]


def test_fits_gives_filler_1fr() -> None:
    heights = allocate_panel_heights([5, 8], [False, False], 30, filler_idx=1)
    assert _scalars(heights) == [(7.0, "cells"), (1.0, "fr")]


def test_fits_first_panel_filler() -> None:
    heights = allocate_panel_heights([5, 8], [False, False], 30, filler_idx=0)
    assert _scalars(heights) == [(1.0, "fr"), (10.0, "cells")]


def test_all_collapsed_has_no_filler() -> None:
    heights = allocate_panel_heights([5, 8], [True, True], 30, filler_idx=0)
    assert _scalars(heights) == [(2.0, "cells"), (2.0, "cells")]


def test_overflow_fixes_smallest_first() -> None:
    # Natural: 7 + 10 + 1 separator = 18 > 15. Panel 0 fixes at 7,
    # panel 1 takes a fractional weight of rows + 1.
    heights = allocate_panel_heights([5, 8], [False, False], 15, filler_idx=1)
    assert _scalars(heights) == [(7.0, "cells"), (9.0, "fr")]


def test_below_minimum_falls_back_to_fractions() -> None:
    heights = allocate_panel_heights([20, 20], [False, False], 5, filler_idx=1)
    assert _scalars(heights) == [(21.0, "fr"), (21.0, "fr")]


def test_zero_container_height_returns_none() -> None:
    assert allocate_panel_heights([5, 8], [False, False], 0, filler_idx=1) is None


def test_empty_panels_returns_empty() -> None:
    assert allocate_panel_heights([], [], 30, filler_idx=0) == []


def test_to_scalar_round_trip() -> None:
    heights = allocate_panel_heights([5, 8], [False, False], 30, filler_idx=1)
    assert heights is not None
    scalars = [h.to_scalar() for h in heights]
    assert scalars[0].unit.name == "CELLS"
    assert scalars[1].unit.name == "FRACTION"


def test_sidebar_width_takes_widest_panel() -> None:
    assert services_sidebar_width([40, 55], terminal_width=200) == 55


def test_sidebar_width_clamps_to_min() -> None:
    assert services_sidebar_width([10], terminal_width=200) == MIN_BGCMD_LIST_WIDTH


def test_sidebar_width_clamps_to_max() -> None:
    assert services_sidebar_width([500], terminal_width=2000) == MAX_BGCMD_LIST_WIDTH


def test_sidebar_width_reserves_dashboard_on_narrow_terminal() -> None:
    assert services_sidebar_width([75], terminal_width=80) == 80 - 40


def test_sidebar_width_keeps_min_on_tiny_terminal() -> None:
    assert services_sidebar_width([60], terminal_width=20) == MIN_BGCMD_LIST_WIDTH


def test_sidebar_width_ignores_non_positive_requests() -> None:
    assert services_sidebar_width([0, 0], terminal_width=200) == MIN_BGCMD_LIST_WIDTH
