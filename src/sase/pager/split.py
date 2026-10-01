"""Pure split-pane layout model for the pager (no Textual imports).

Mirrors the Agents deck split shapes (``decks/layout.py``) without importing
them: the pager owns its own two-pane peer model with its own key semantics
(same key keeps the focused pane, ``+``/``-`` instead of ``{``/``}``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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

    ``focused`` is the index of the pane that receives keys (0 or 1; always
    0 when single). ``ratio`` is the first pane's share in percent, drawn
    from :data:`RATIO_STEPS`.
    """

    layout: PagerSplitLayout = PagerSplitLayout.SINGLE
    focused: int = 0
    ratio: int = 50


def initial_split_state() -> PagerSplitState:
    """Return the default single-pane state."""
    return PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50)


def toggle_split(state: PagerSplitState, target: PagerSplitLayout) -> PagerSplitState:
    """Toggle a split for *target* following the pager key table.

    From single, open *target* with the new pane focused at 50/50. Pressing
    the same key again closes the other pane and keeps the focused one (the
    survivor becomes index 0). Pressing the other key rotates, keeping
    focus and ratio.
    """
    if state.layout is PagerSplitLayout.SINGLE:
        return PagerSplitState(layout=target, focused=1, ratio=50)
    if state.layout is target:
        return PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50)
    return PagerSplitState(layout=target, focused=state.focused, ratio=state.ratio)


def close_focused_pane(state: PagerSplitState) -> PagerSplitState:
    """Close the focused pane, leaving a single pane focused at index 0."""
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    return PagerSplitState(layout=PagerSplitLayout.SINGLE, focused=0, ratio=50)


def toggle_focus(state: PagerSplitState) -> PagerSplitState:
    """Focus the other pane; a no-op when single."""
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    return PagerSplitState(
        layout=state.layout,
        focused=1 - state.focused,
        ratio=state.ratio,
    )


def step_ratio(state: PagerSplitState, direction: int) -> PagerSplitState:
    """Grow (``+1``) or shrink (``-1``) the focused pane one ratio step.

    The ratio is the first pane's share, so growing pane 0 steps up while
    growing pane 1 steps down. The ends clamp; a single pane never moves.
    """
    if state.layout is PagerSplitLayout.SINGLE:
        return state
    if direction == 0:
        return state
    steps = list(RATIO_STEPS)
    try:
        position = steps.index(state.ratio)
    except ValueError:
        position = min(range(len(steps)), key=lambda i: abs(steps[i] - state.ratio))
    if state.focused == 0:
        position += 1 if direction > 0 else -1
    else:
        position -= 1 if direction > 0 else -1
    position = max(0, min(len(steps) - 1, position))
    return PagerSplitState(
        layout=state.layout, focused=state.focused, ratio=steps[position]
    )


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


__all__ = [
    "MIN_BESIDE_PANE_WIDTH",
    "MIN_STACKED_PANE_HEIGHT",
    "PagerSplitLayout",
    "PagerSplitState",
    "RATIO_STEPS",
    "close_focused_pane",
    "initial_split_state",
    "split_fits",
    "step_ratio",
    "toggle_focus",
    "toggle_split",
]
