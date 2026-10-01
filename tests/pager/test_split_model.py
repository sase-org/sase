"""Pure-model tests for the pager split layout."""

from __future__ import annotations

from sase.pager.split import (
    PagerSplitLayout,
    PagerSplitState,
    RATIO_STEPS,
    close_focused_pane,
    initial_split_state,
    split_fits,
    step_ratio,
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


def test_close_focused_leaves_single() -> None:
    opened = toggle_split(initial_split_state(), PagerSplitLayout.BESIDE)
    closed = close_focused_pane(opened)
    assert closed.layout is PagerSplitLayout.SINGLE
    assert closed.focused == 0
    assert close_focused_pane(closed) == closed


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


def test_split_fits_guards_small_windows() -> None:
    assert split_fits(PagerSplitLayout.SINGLE, 50, 10, 5)
    assert split_fits(PagerSplitLayout.BELOW, 50, 120, 40)
    assert split_fits(PagerSplitLayout.BESIDE, 50, 120, 40)
    assert not split_fits(PagerSplitLayout.BELOW, 50, 120, 10)
    assert not split_fits(PagerSplitLayout.BESIDE, 50, 40, 40)
    # Skewed ratios still need both minimums.
    assert not split_fits(PagerSplitLayout.BELOW, 30, 120, 10)
    assert not split_fits(PagerSplitLayout.BESIDE, 70, 40, 40)
