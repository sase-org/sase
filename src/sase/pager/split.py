"""Pager split-pane policy over the shared :mod:`PaneGrid` model.

The pager keeps its own two-pane peer vocabulary (``BELOW``/``BESIDE``,
same key keeps the focused pane, ``+``/``-`` stepping) and its own fit
minimums, but every transition is computed by
:mod:`sase.ace.tui.util.pane_grid` so no second copy of the algebra exists.
No Textual imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sase.ace.tui.util.pane_grid import (
    Axis,
    PaneGrid,
    cycle_focus as _grid_cycle_focus,
    free_pane_id,
    pane_rects,
    press_split as _grid_press_split,
    step_ratio as _grid_step_ratio,
    swap_focused as _grid_swap_focused,
)

RATIO_STEPS: tuple[int, ...] = (30, 50, 70)


#: Minimum framed pane extent at any ratio step. Stacked panes split height,
#: side-by-side panes split width; the frame plus five body rows needs seven
#: rows, and a readable beside split needs about 32 columns per pane.
MIN_STACKED_PANE_HEIGHT = 7
MIN_BESIDE_PANE_WIDTH = 32


class PagerSplitLayout(StrEnum):
    """The pager's pane arrangement."""

    SINGLE = "single"
    BELOW = "below"
    BESIDE = "beside"


@dataclass(frozen=True, slots=True)
class PagerSplitState:
    """One immutable split arrangement.

    ``focused`` is the reading-order slot of the pane that receives keys
    (always 0 when single). ``ratio`` is the first pane's share in
    percent, drawn from :data:`RATIO_STEPS`. Three-pane grids read as
    their outer shape here; the pair geometry lives on the grid.
    """

    layout: PagerSplitLayout = PagerSplitLayout.SINGLE
    focused: int = 0
    ratio: int = 50


def initial_split_state() -> PagerSplitState:
    """Return the default single-pane state."""
    return PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50)


def split_axis(layout: PagerSplitLayout) -> Axis | None:
    """Map a pager layout to its :class:`PaneGrid` divider axis."""
    if layout is PagerSplitLayout.BELOW:
        return Axis.ROWS
    if layout is PagerSplitLayout.BESIDE:
        return Axis.COLS
    return None


def layout_for_axis(axis: Axis | None) -> PagerSplitLayout:
    """Map a :class:`PaneGrid` divider axis back to a pager layout."""
    if axis is Axis.ROWS:
        return PagerSplitLayout.BELOW
    if axis is Axis.COLS:
        return PagerSplitLayout.BESIDE
    return PagerSplitLayout.SINGLE


def _grid_for_state(state: PagerSplitState) -> PaneGrid:
    """Map a two-pane pager state onto its :class:`PaneGrid`.

    Pane IDs are the reading-order slot indices (``0`` single, else
    ``(0, 1)``); ``focused`` becomes the focused pane ID and ``recent``
    puts it first.
    """
    if state.layout is PagerSplitLayout.SINGLE:
        return PaneGrid(panes=(0,), focused=0, recent=(0,))
    axis = split_axis(state.layout)
    focused = 1 if state.focused == 1 else 0
    other = 1 - focused
    return PaneGrid(
        panes=(0, 1),
        focused=focused,
        axis=axis,
        ratio=state.ratio,
        recent=(focused, other),
    )


def state_for_grid(grid: PaneGrid) -> PagerSplitState:
    """Map a :class:`PaneGrid` back to pager state.

    Three-pane grids read as their outer two-pane shape: the layout names
    the outer axis, ``focused`` is the reading-order slot, and ``ratio``
    is the outer ratio. The pair geometry lives on the grid itself.
    """
    if len(grid.panes) == 3 and grid.axis is not None:
        try:
            focused = grid.panes.index(grid.focused)
        except ValueError:
            focused = 0
        return PagerSplitState(
            layout=layout_for_axis(grid.axis), focused=focused, ratio=grid.ratio
        )
    if len(grid.panes) != 2 or grid.axis is None:
        return PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50)
    try:
        focused = grid.panes.index(grid.focused)
    except ValueError:
        focused = 0
    return PagerSplitState(
        layout=layout_for_axis(grid.axis), focused=focused, ratio=grid.ratio
    )


def toggle_split(state: PagerSplitState, target: PagerSplitLayout) -> PagerSplitState:
    """Toggle a split for *target* following the pager key table.

    From single, open *target* with the new pane focused at 50/50. Pressing
    the same key again closes the other pane and keeps the focused one (the
    survivor becomes index 0). Pressing the other key on a two-pane split
    nests a third pane; the returned state names the outer shape and the
    pair geometry lives on the grid. Computed on :class:`PaneGrid`.
    """
    grid = _grid_for_state(state)
    axis = split_axis(target)
    if axis is None:
        return state
    if len(grid.panes) <= 1:
        new_id = free_pane_id(grid)
        if new_id is None:
            return state
        return state_for_grid(_grid_press_split(grid, axis, new_id))
    if axis is not grid.axis:
        new_id = free_pane_id(grid)
        if new_id is None:
            return state
        return state_for_grid(_grid_press_split(grid, axis, new_id))
    return state_for_grid(_grid_press_split(grid, axis, grid.focused))


def toggle_focus(state: PagerSplitState) -> PagerSplitState:
    """Focus the other pane; a no-op when single."""
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    return state_for_grid(_grid_cycle_focus(_grid_for_state(state), 1))


def swap_focused(state: PagerSplitState, step: int) -> PagerSplitState:
    """Exchange the focused pane with its neighbour *step* away.

    Geometry and ratio belong to slots and do not change; focus follows
    the content. A no-op when single.
    """
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    return state_for_grid(_grid_swap_focused(_grid_for_state(state), step))


def step_ratio(state: PagerSplitState, direction: int) -> PagerSplitState:
    """Grow (``+1``) or shrink (``-1``) the focused pane one ratio step.

    The ratio is the first pane's share, so growing pane 0 steps up while
    growing pane 1 steps down. The ends clamp; a single pane never moves.
    """
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    if direction == 0:
        return state
    grid = _grid_for_state(state)
    candidate = _grid_step_ratio(grid, grow=direction > 0)
    if candidate == grid:
        return state
    return state_for_grid(candidate)


def split_fits(
    layout: PagerSplitLayout,
    ratio: int,
    width: int,
    height: int,
) -> bool:
    """Return whether *layout* at *ratio* fits in *width* x *height*."""
    if layout is PagerSplitLayout.SINGLE:
        return True
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        return False
    if layout is PagerSplitLayout.BELOW:
        first = height * int(ratio) // 100
        second = height - first
        return first >= MIN_STACKED_PANE_HEIGHT and second >= MIN_STACKED_PANE_HEIGHT
    first = width * int(ratio) // 100
    second = width - first
    return first >= MIN_BESIDE_PANE_WIDTH and second >= MIN_BESIDE_PANE_WIDTH


def pager_grid_fits(grid: PaneGrid, width: int, height: int) -> bool:
    """Return whether every pane of *grid* meets the pager minimums.

    Stacked panes need ``MIN_STACKED_PANE_HEIGHT`` rows each and
    side-by-side panes ``MIN_BESIDE_PANE_WIDTH`` columns each, measured
    with the shared ``pane_rects`` floor rule so it agrees exactly with
    :func:`split_fits` on one- and two-pane grids. A new three-pane
    geometry needs both minimums in every pane.
    """
    if len(grid.panes) <= 1 or grid.axis is None:
        return True
    rects = pane_rects(grid, width, height)
    if len(grid.panes) == 3:
        return all(
            w >= MIN_BESIDE_PANE_WIDTH and h >= MIN_STACKED_PANE_HEIGHT
            for (_, _, w, h) in rects.values()
        )
    if grid.axis is Axis.ROWS:
        return all(h >= MIN_STACKED_PANE_HEIGHT for (_, _, _, h) in rects.values())
    return all(w >= MIN_BESIDE_PANE_WIDTH for (_, _, w, _) in rects.values())


__all__ = [
    "MIN_BESIDE_PANE_WIDTH",
    "MIN_STACKED_PANE_HEIGHT",
    "PagerSplitLayout",
    "PagerSplitState",
    "RATIO_STEPS",
    "initial_split_state",
    "layout_for_axis",
    "pager_grid_fits",
    "split_axis",
    "split_fits",
    "state_for_grid",
    "step_ratio",
    "swap_focused",
    "toggle_focus",
    "toggle_split",
]
