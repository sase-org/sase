"""Hypothesis invariants for the shared PaneGrid split algebra."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from sase.ace.tui.util.pane_grid import (
    MAX_PANES,
    RATIO_STEPS,
    Axis,
    Pair,
    PaneGrid,
    close_focused,
    cycle_focus,
    focus_pane,
    free_pane_id,
    _geometry,
    grid_spec,
    pane_rects,
    press_split,
    step_ratio,
    swap_focused,
    turn,
)

_IDS = list(range(MAX_PANES))


@st.composite
def _grids(draw):
    from itertools import permutations

    n = draw(st.integers(min_value=1, max_value=MAX_PANES))
    panes = draw(st.sampled_from([tuple(p) for p in permutations(_IDS, n)]))
    focused = draw(st.sampled_from(panes))
    rest = draw(st.permutations([p for p in panes if p != focused]))
    axis: Axis | None = None
    ratio = 50
    pair: Pair | None = None
    if n == 1:
        recent = (focused,)
    elif n == 2:
        axis = draw(st.sampled_from([Axis.ROWS, Axis.COLS]))
        ratio = draw(st.sampled_from(list(RATIO_STEPS)))
        recent = (focused, *rest)
    else:
        axis = draw(st.sampled_from([Axis.ROWS, Axis.COLS]))
        ratio = draw(st.sampled_from(list(RATIO_STEPS)))
        region = draw(st.integers(min_value=0, max_value=1))
        pair_ratio = draw(st.sampled_from(list(RATIO_STEPS)))
        pair = Pair(region=region, ratio=pair_ratio)
        recent = (focused, *rest)
    return PaneGrid(
        panes=panes, focused=focused, axis=axis, ratio=ratio, pair=pair, recent=recent
    )


grids = _grids()


def _assert_valid(g: PaneGrid) -> None:
    assert 1 <= len(g.panes) <= MAX_PANES
    assert len(set(g.panes)) == len(g.panes)
    assert all(p in _IDS for p in g.panes)
    assert g.focused in g.panes
    assert tuple(sorted(g.recent)) == tuple(sorted(g.panes))
    assert g.recent[0] == g.focused
    assert (g.axis is None) == (len(g.panes) == 1)
    assert (g.pair is None) == (len(g.panes) != 3)
    assert g.ratio in RATIO_STEPS
    if g.pair is not None:
        assert g.pair.region in (0, 1)
        assert g.pair.ratio in RATIO_STEPS


_OPS = [
    "split-rows",
    "split-cols",
    "close",
    "focus+",
    "focus-",
    "swap+",
    "swap-",
    "turn",
    "grow",
    "shrink",
    "goto-0",
    "goto-1",
    "goto-2",
]


def _apply(g: PaneGrid, op: str) -> PaneGrid:
    if op == "split-rows":
        new_id = free_pane_id(g)
        return press_split(g, Axis.ROWS, new_id if new_id is not None else -1)
    if op == "split-cols":
        new_id = free_pane_id(g)
        return press_split(g, Axis.COLS, new_id if new_id is not None else -1)
    if op == "close":
        return close_focused(g)
    if op == "focus+":
        return cycle_focus(g, 1)
    if op == "focus-":
        return cycle_focus(g, -1)
    if op == "swap+":
        return swap_focused(g, 1)
    if op == "swap-":
        return swap_focused(g, -1)
    if op == "turn":
        return turn(g)
    if op == "grow":
        return step_ratio(g, True)
    if op == "shrink":
        return step_ratio(g, False)
    return focus_pane(g, int(op.rsplit("-", 1)[1]))


@given(grids)
def test_outputs_stay_valid(g: PaneGrid) -> None:
    """Every transition keeps a valid grid and never yields four panes."""
    _assert_valid(g)
    for op in _OPS:
        after = _apply(g, op)
        _assert_valid(after)
        assert len(after.panes) <= MAX_PANES


@given(grids)
def test_turn_is_self_inverse(g: PaneGrid) -> None:
    assert turn(turn(g)) == g


@given(grids)
def test_swap_round_trip(g: PaneGrid) -> None:
    assert swap_focused(swap_focused(g, 1), -1) == g
    assert swap_focused(swap_focused(g, -1), 1) == g


@given(grids)
def test_close_is_inverse_of_split(g: PaneGrid) -> None:
    """close after split returns ratios, focus, and MRU from 1- and 2-panes."""
    if len(g.panes) == 1:
        for axis in (Axis.ROWS, Axis.COLS):
            new_id = free_pane_id(g)
            assert new_id is not None
            assert close_focused(press_split(g, axis, new_id)) == g
    elif len(g.panes) == 2 and g.axis is not None:
        other = Axis.COLS if g.axis is Axis.ROWS else Axis.ROWS
        new_id = free_pane_id(g)
        assert new_id is not None
        assert close_focused(press_split(g, other, new_id)) == g


@given(grids)
def test_focus_cycle_visits_every_pane(g: PaneGrid) -> None:
    """n focus steps visit every pane and return focus to the start."""
    seen = set()
    current = g
    for _ in range(len(g.panes)):
        seen.add(current.focused)
        current = cycle_focus(current, 1)
    assert seen == set(g.panes)
    assert current.focused == g.focused


@given(grids)
def test_grid_spec_tiles_without_gap_or_overlap(g: PaneGrid) -> None:
    """grid_spec cells tile the track grid exactly once."""
    spec = grid_spec(g)
    ncols = len(spec.columns)
    nrows = len(spec.rows)
    assert ncols >= 1 and nrows >= 1
    covered: dict[tuple[int, int], int] = {}
    for pane_id in g.panes:
        col, row, cspan, rspan = spec.cells[pane_id]
        assert col >= 0 and row >= 0 and cspan >= 1 and rspan >= 1
        assert col + cspan <= ncols and row + rspan <= nrows
        for c in range(col, col + cspan):
            for r in range(row, row + rspan):
                covered[(c, r)] = covered.get((c, r), 0) + 1
    assert len(covered) == ncols * nrows
    assert set(covered.values()) == {1}
    assert tuple(sorted(spec.dom_order)) == tuple(sorted(g.panes))


@given(
    grids,
    st.integers(min_value=1, max_value=300),
    st.integers(min_value=1, max_value=120),
)
def test_pane_rects_tile_exactly(g: PaneGrid, width: int, height: int) -> None:
    """pane_rects tile width x height with no gap or overlap.

    Absurdly small areas may starve a pane to zero extent under the floor
    rule (the pager ``split_fits`` arithmetic this mirrors); ``fits()`` is
    the guard that refuses such geometries. Coverage is still exact.
    """
    rects = pane_rects(g, width, height)
    assert set(rects) == set(g.panes)
    covered: dict[tuple[int, int], int] = {}
    for x, y, w, h in rects.values():
        assert x >= 0 and y >= 0 and w >= 0 and h >= 0
        assert x + w <= width and y + h <= height
        for c in range(x, x + w):
            for r in range(y, y + h):
                covered[(c, r)] = covered.get((c, r), 0) + 1
    assert len(covered) == width * height
    assert set(covered.values()) == {1}


@given(st.lists(st.sampled_from(_OPS), min_size=1, max_size=25))
def test_random_sequences_never_raise(ops: list[str]) -> None:
    """Long random key sequences stay valid, single or not."""
    g = PaneGrid()
    for op in ops:
        g = _apply(g, op)
        _assert_valid(g)
    assert _geometry(g).value in {
        "single",
        "R2",
        "C2",
        "R3-main-top",
        "R3-main-bottom",
        "C3-main-left",
        "C3-main-right",
    }
