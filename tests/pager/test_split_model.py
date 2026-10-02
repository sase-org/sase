"""Pure-model tests for the pager split layout."""

from __future__ import annotations

from sase.ace.tui.util.pane_grid import Axis, PaneGrid
from sase.pager.split import (
    PagerSplitLayout,
    PagerSplitState,
    RATIO_STEPS,
    initial_split_state,
    layout_for_axis,
    pager_grid_fits,
    split_axis,
    split_fits,
    state_for_grid,
    step_ratio,
    swap_focused,
    toggle_focus,
    toggle_split,
)


def test_initial_state_is_single() -> None:
    state = initial_split_state()
    assert state.layout is PagerSplitLayout.SINGLE
    assert state.focused == 0
    assert state.ratio == 50


def test_open_below_focuses_new_pane() -> None:
    state = toggle_split(initial_split_state(), PagerSplitLayout.BELOW)
    assert state.layout is PagerSplitLayout.BELOW
    assert state.focused == 1
    assert state.ratio == 50


def test_same_key_keeps_focused_pane_as_single() -> None:
    opened = toggle_split(initial_split_state(), PagerSplitLayout.BELOW)
    closed = toggle_split(opened, PagerSplitLayout.BELOW)
    assert closed.layout is PagerSplitLayout.SINGLE
    assert closed.focused == 0


def test_other_key_rotates_keeping_focus_and_ratio() -> None:
    opened = PagerSplitState(layout=PagerSplitLayout.BELOW, focused=1, ratio=30)
    rotated = toggle_split(opened, PagerSplitLayout.BESIDE)
    assert rotated.layout is PagerSplitLayout.BESIDE
    assert rotated.focused == 1
    assert rotated.ratio == 30


def test_toggle_focus_swaps_panes() -> None:
    opened = toggle_split(initial_split_state(), PagerSplitLayout.BELOW)
    assert toggle_focus(opened).focused == 0
    assert toggle_focus(toggle_focus(opened)) == opened
    assert toggle_focus(initial_split_state()) == initial_split_state()


def test_step_ratio_grows_focused_pane_and_clamps() -> None:
    below = PagerSplitState(layout=PagerSplitLayout.BELOW, focused=0, ratio=50)
    assert step_ratio(below, +1).ratio == 70
    assert step_ratio(step_ratio(below, +1), +1).ratio == 70
    assert step_ratio(below, -1).ratio == 30
    # Growing pane 1 steps the first-pane share down.
    other = PagerSplitState(layout=PagerSplitLayout.BELOW, focused=1, ratio=50)
    assert step_ratio(other, +1).ratio == 30
    assert step_ratio(other, -1).ratio == 70
    assert step_ratio(initial_split_state(), +1) == initial_split_state()


def test_ratio_steps_match_agents_deck() -> None:
    assert RATIO_STEPS == (30, 50, 70)


def test_state_for_grid_reads_two_pane_grids() -> None:
    cases = (
        (
            PaneGrid(),
            PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50),
        ),
        (
            PaneGrid(
                panes=(0, 1),
                focused=1,
                axis=Axis.ROWS,
                ratio=50,
                recent=(1, 0),
            ),
            PagerSplitState(layout=PagerSplitLayout.BELOW, focused=1, ratio=50),
        ),
        (
            PaneGrid(
                panes=(0, 1),
                focused=0,
                axis=Axis.COLS,
                ratio=30,
                recent=(0, 1),
            ),
            PagerSplitState(layout=PagerSplitLayout.BESIDE, focused=0, ratio=30),
        ),
        # Live pane IDs are not slot indices (close keeps the survivor's
        # ID): focus still maps by reading-order slot.
        (
            PaneGrid(
                panes=(1, 0),
                focused=0,
                axis=Axis.ROWS,
                ratio=50,
                recent=(0, 1),
            ),
            PagerSplitState(layout=PagerSplitLayout.BELOW, focused=1, ratio=50),
        ),
    )
    for grid, state in cases:
        assert state_for_grid(grid) == state


def test_axis_mapping_covers_all_layouts() -> None:
    assert split_axis(PagerSplitLayout.BELOW) is not None
    assert split_axis(PagerSplitLayout.BESIDE) is not None
    assert split_axis(PagerSplitLayout.SINGLE) is None
    assert layout_for_axis(split_axis(PagerSplitLayout.BELOW)) is (
        PagerSplitLayout.BELOW
    )
    assert layout_for_axis(split_axis(PagerSplitLayout.BESIDE)) is (
        PagerSplitLayout.BESIDE
    )


def _slot_grid(state: PagerSplitState) -> PaneGrid:
    """Build the slot-indexed grid for a two-pane pager state (test only)."""
    if state.layout is PagerSplitLayout.SINGLE:
        return PaneGrid()
    axis = Axis.ROWS if state.layout is PagerSplitLayout.BELOW else Axis.COLS
    focused = 1 if state.focused == 1 else 0
    return PaneGrid(
        panes=(0, 1),
        focused=focused,
        axis=axis,
        ratio=state.ratio,
        recent=(focused, 1 - focused),
    )


def test_pager_grid_fits_matches_split_fits() -> None:
    states = (
        initial_split_state(),
        PagerSplitState(layout=PagerSplitLayout.BELOW, focused=1, ratio=50),
        PagerSplitState(layout=PagerSplitLayout.BESIDE, focused=0, ratio=30),
        PagerSplitState(layout=PagerSplitLayout.BESIDE, focused=1, ratio=70),
    )
    areas = ((120, 40), (120, 10), (40, 40), (60, 30), (0, 0))
    for state in states:
        grid = _slot_grid(state)
        for width, height in areas:
            assert pager_grid_fits(grid, width, height) == split_fits(
                state.layout, state.ratio, width, height
            )


def test_two_pane_swap_helper() -> None:
    below = toggle_split(initial_split_state(), PagerSplitLayout.BELOW)
    swapped = swap_focused(below, 1)
    assert swapped.layout is PagerSplitLayout.BELOW
    assert swapped.ratio == below.ratio
    # The focused slot flips; stable pane-ID tracking lives in the
    # screen's pane-ID-keyed views, covered by the Pilot swap test.
    assert swapped.focused == 0
    assert swap_focused(swapped, -1) == below
    assert swap_focused(initial_split_state(), 1) == initial_split_state()


def test_split_fits_guards_small_windows() -> None:
    assert split_fits(PagerSplitLayout.SINGLE, 50, 10, 5)
    assert split_fits(PagerSplitLayout.BELOW, 50, 120, 40)
    assert split_fits(PagerSplitLayout.BESIDE, 50, 120, 40)
    assert not split_fits(PagerSplitLayout.BELOW, 50, 120, 10)
    assert not split_fits(PagerSplitLayout.BESIDE, 50, 40, 40)
    # Skewed ratios still need both minimums.
    assert not split_fits(PagerSplitLayout.BELOW, 30, 120, 10)
    assert not split_fits(PagerSplitLayout.BESIDE, 70, 40, 40)
