"""Pure deck split layout transitions."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from enum import Enum

from sase.ace.tui.util import pane_grid
from sase.ace.tui.util.pane_grid import (
    Axis,
    PaneGrid,
    close_focused,
    cycle_focus,
    fits,
    focus_pane,
    free_pane_id,
    press_split,
    swap_focused,
    turn,
)

from .model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
    cycle_card_id,
    panel_state,
)

RATIO_STEPS: tuple[int, ...] = (30, 50, 70)

#: Minimum deck-panel extent a new three-pane geometry must grant every
#: panel. The two-panel path stays unguarded, and shrinking the terminal
#: never closes a pane.
MIN_DECK_PANEL_HEIGHT = 8
MIN_DECK_PANEL_WIDTH = 40


def three_pane_splits_enabled() -> bool:
    """Return whether the ``three_pane_splits`` beta flag is enabled.

    Resolved at the use site on every call, never at module import time,
    so cold-path import-weight tests stay green.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags
    except Exception:
        return False
    try:
        return bool(current_flags().enabled(FeatureFlag.three_pane_splits))
    except Exception:
        return False


def _axis_for_layout(target: DeckLayout) -> Axis:
    """Return the grid axis a split key for ``target`` draws."""
    if target is DeckLayout.LEFT_RIGHT:
        return Axis.COLS
    return Axis.ROWS


class SidebarMode(Enum):
    """Left-column presentation derived from deck-area state."""

    EXPANDED = "expanded"
    RAIL = "rail"
    HIDDEN = "hidden"


def sidebar_mode(state: DeckAreaState) -> SidebarMode:
    """Derive the sidebar mode: HIDDEN when zoomed, else RAIL when collapsed."""
    if state.zoom_snapshot is not None:
        return SidebarMode.HIDDEN
    if state.nodes_collapsed:
        return SidebarMode.RAIL
    return SidebarMode.EXPANDED


def choose_new_panel(
    current_deck: DeckId,
    current_active_card: str | None,
    shown: Sequence[DeckId] | set[DeckId] | frozenset[DeckId],
    has_content: Mapping[DeckId, bool | None],
    card_ids: Sequence[str],
) -> DeckPanelState:
    """Choose the deck for a newly opened panel.

    Walk the active deck cycle forward from ``current_deck`` and pick the
    first deck that is not in ``shown`` and whose ``has_content`` entry is
    not ``False``. Unknown (``None`` or missing) counts as content, except
    for FINAL, which a fresh split takes only on positive content — an
    empty FINAL ("No finalizers for this agent") is never the triage
    loop's second panel. When none qualifies, duplicate ``current_deck``
    on the card after ``current_active_card``.
    """
    from .spec import active_deck_cycle

    cycle = active_deck_cycle()
    shown_set = set(shown)
    try:
        start = cycle.index(current_deck)
    except ValueError:
        start = -1
    for offset in range(1, len(cycle) + 1):
        candidate = cycle[(start + offset) % len(cycle)]
        if candidate in shown_set:
            continue
        try:
            content = has_content[candidate]
        except Exception:
            content = None
        if content is False:
            continue
        if candidate is DeckId.FINAL and content is not True:
            continue
        return DeckPanelState(deck=candidate)
    return new_panel_for_deck(current_deck, current_deck, current_active_card, card_ids)


def new_panel_for_deck(
    deck: DeckId,
    current_deck: DeckId,
    current_active_card: str | None,
    card_ids: Sequence[str],
) -> DeckPanelState:
    """Return the state for a new panel that shows ``deck``.

    A duplicate Main panel prefers the card after ``current_active_card`` so
    the two panels open on different cards. Every other panel has no
    preferred card.
    """
    if deck is DeckId.MAIN and current_deck is DeckId.MAIN:
        next_card = cycle_card_id(tuple(card_ids), current_active_card, 1)
        if next_card is None:
            return DeckPanelState(deck=deck)
        return DeckPanelState(deck=deck, preferred_cards={DeckId.MAIN: next_card})
    return DeckPanelState(deck=deck)


def toggle_split(
    state: DeckAreaState,
    target: DeckLayout,
    new_panel: DeckPanelState,
    *,
    focus_new: bool = True,
    nest: bool = False,
) -> DeckAreaState:
    """Toggle a split layout for ``target``.

    From SINGLE open ``new_panel`` on a free pane ID with a 50/50 ratio.
    The new pane takes focus unless ``focus_new`` is false (unsplit and
    rotate ignore the flag). Pressing the same layout key again unsplits,
    keeping the focused panel. Pressing the other layout key rotates when
    ``nest`` is false, or nests ``new_panel`` into a three-pane T layout
    when ``nest`` is true (the ``three_pane_splits`` beta flag). With
    three panes, the outer-axis key erases the full-span divider and the
    other key turns the layout. A layout key while zoomed only restores
    the snapshot, keeping panels edited while zoomed.
    """
    if state.zoom_snapshot is not None:
        return exit_zoom_keeping_panels(state)
    axis = _axis_for_layout(target)
    if state.layout is DeckLayout.SINGLE:
        new_id = free_pane_id(state.grid)
        if new_id is None:
            return state
        pressed = press_split(state.grid, axis, new_id, nest=nest)
        if len(pressed.panes) < 2:
            return state
        if not focus_new:
            pressed = focus_pane(pressed, state.grid.focused)
        panels = dict(state.panels)
        panels[new_id] = new_panel
        return dataclasses.replace(state, grid=pressed, panels=panels)
    if (
        nest
        and len(state.grid.panes) == 2
        and state.grid.axis is not None
        and axis is not state.grid.axis
    ):
        new_id = free_pane_id(state.grid)
        if new_id is None:
            return state
        pressed = press_split(state.grid, axis, new_id, nest=True)
        if len(pressed.panes) != 3:
            return state
        if not focus_new:
            pressed = focus_pane(pressed, state.grid.focused)
        panels = dict(state.panels)
        panels[new_id] = new_panel
        return dataclasses.replace(state, grid=pressed, panels=panels)
    pressed = press_split(state.grid, axis, state.grid.focused, nest=nest)
    if len(pressed.panes) < 2:
        focused = pressed.focused
        return dataclasses.replace(
            state, grid=pressed, panels={focused: panel_state(state, focused)}
        )
    return dataclasses.replace(state, grid=pressed)


def _nest_or_turn_result(
    state: DeckAreaState, target: DeckLayout, *, nest: bool
) -> PaneGrid | None:
    """Return the grid a split key for ``target`` would commit, if guarded.

    Returns None when the key needs no fit guard: zoomed restores, single
    opens an unguarded two-pane split, same-key unsplits, and flag-off
    rotates only ever shrink to fewer panes.
    """
    if state.zoom_snapshot is not None:
        return None
    axis = _axis_for_layout(target)
    grid = state.grid
    if len(grid.panes) < 2:
        return None
    if len(grid.panes) == 2:
        if axis == grid.axis or not nest:
            return None
        new_id = free_pane_id(grid)
        if new_id is None:
            return None
        nested = press_split(grid, axis, new_id, nest=True)
        return nested if len(nested.panes) == 3 else None
    turned = press_split(grid, axis, grid.focused, nest=nest)
    return turned if len(turned.panes) == 3 else None


def refuse_three_pane_key(
    state: DeckAreaState,
    target: DeckLayout,
    width: int,
    height: int,
    *,
    nest: bool,
    collapsed_gain: int = 0,
) -> str | None:
    """Return a refusal toast when a split key must not commit, else None.

    Only a nest into three panes or a three-pane turn is ever refused, and
    only when the resulting grid would starve a panel below
    ``MIN_DECK_PANEL_HEIGHT`` × ``MIN_DECK_PANEL_WIDTH``. Unknown sizes
    fail open. When collapsing the node list would reclaim enough width,
    the message says so.
    """
    if width <= 0 or height <= 0:
        return None
    result = _nest_or_turn_result(state, target, nest=nest)
    if result is None:
        return None
    if fits(
        result,
        width,
        height,
        min_width=MIN_DECK_PANEL_WIDTH,
        min_height=MIN_DECK_PANEL_HEIGHT,
    ):
        return None
    if len(state.grid.panes) == 2:
        message = "Not enough room for a third panel"
    else:
        message = "Not enough room to turn the panels"
    if (
        collapsed_gain > 0
        and not state.nodes_collapsed
        and fits(
            result,
            width + collapsed_gain,
            height,
            min_width=MIN_DECK_PANEL_WIDTH,
            min_height=MIN_DECK_PANEL_HEIGHT,
        )
    ):
        message += " \u2014 ctrl+s collapses the node list"
    return message


def refuse_turn(state: DeckAreaState, width: int, height: int) -> str | None:
    """Return a refusal toast when ``ctrl+t`` must not commit, else None.

    Only a three-pane turn is ever refused. Unknown sizes fail open.
    """
    if width <= 0 or height <= 0:
        return None
    if len(state.grid.panes) != 3 or state.zoom_snapshot is not None:
        return None
    turned = turn(state.grid)
    if fits(
        turned,
        width,
        height,
        min_width=MIN_DECK_PANEL_WIDTH,
        min_height=MIN_DECK_PANEL_HEIGHT,
    ):
        return None
    return "Not enough room to turn the panels"


def toggle_nodes_collapsed(state: DeckAreaState) -> DeckAreaState:
    """Toggle the node panel between expanded and rail without unmounting it.

    While zoomed, Ctrl+S restores the snapshot exactly, like Z.
    """
    if state.zoom_snapshot is not None:
        return _exit_zoom(state)
    return dataclasses.replace(state, nodes_collapsed=not state.nodes_collapsed)


def is_zoomed(state: DeckAreaState) -> bool:
    """Return whether ``state`` is a zoomed snapshot view."""
    return state.zoom_snapshot is not None


def _enter_zoom(state: DeckAreaState, focused: int | None = None) -> DeckAreaState:
    """Zoom the focused pane in place, hiding the node panel or rail.

    Snapshots the deck-area state (grid, panels, collapse) and shows only
    the zoomed pane. Hidden panes keep their widgets and sessions in the
    panels map. The ``nodes_collapsed`` preference is left untouched so
    zoom never leaks into it. A second ``Z`` restores the snapshot exactly
    via :func:`_exit_zoom`.
    """
    if state.zoom_snapshot is not None:
        return state
    snapshot = dataclasses.replace(state, zoom_snapshot=None)
    pane_id = snapshot.focused if focused is None else focused
    if pane_id not in snapshot.grid.panes:
        pane_id = snapshot.focused
    zoomed_grid = PaneGrid(panes=(pane_id,), focused=pane_id, recent=(pane_id,))
    return dataclasses.replace(
        snapshot,
        grid=zoomed_grid,
        zoom_snapshot=snapshot,
    )


def _exit_zoom(state: DeckAreaState) -> DeckAreaState:
    """Restore the snapshot taken by :func:`_enter_zoom`."""
    if state.zoom_snapshot is None:
        return state
    return state.zoom_snapshot


def exit_zoom_keeping_panels(state: DeckAreaState) -> DeckAreaState:
    """End a zoom, restoring the snapshot's layout but keeping current panels.

    Unlike :func:`_exit_zoom`, the current panels and focus survive so a
    deck changed while zoomed is not lost. An unzoomed state is returned
    unchanged.
    """
    snapshot = state.zoom_snapshot
    if snapshot is None:
        return state
    grid = focus_pane(snapshot.grid, state.grid.focused)
    return dataclasses.replace(snapshot, grid=grid, panels=dict(state.panels))


def toggle_zoom(state: DeckAreaState, focused: int | None = None) -> DeckAreaState:
    """Enter the zoom, or restore the snapshot when already zoomed."""
    if state.zoom_snapshot is not None:
        return _exit_zoom(state)
    return _enter_zoom(state, focused)


def toggle_focus(state: DeckAreaState) -> DeckAreaState:
    """Move logical focus to the next pane in reading order (wraps)."""
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    return dataclasses.replace(state, grid=cycle_focus(state.grid, 1))


def toggle_focus_reverse(state: DeckAreaState) -> DeckAreaState:
    """Move logical focus to the previous pane in reading order (wraps)."""
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    return dataclasses.replace(state, grid=cycle_focus(state.grid, -1))


def swap_deck_panel(state: DeckAreaState, direction: int) -> DeckAreaState:
    """Exchange the focused pane's session with the neighbour ``direction`` away.

    Geometry and both ratios belong to slots and do not change; the widgets
    move cells and keep their content, so focus follows the content.
    """
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    return dataclasses.replace(state, grid=swap_focused(state.grid, direction))


def close_deck_panel(state: DeckAreaState) -> DeckAreaState:
    """Close the focused pane, dropping its session; inert unless split."""
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    grid = close_focused(state.grid)
    panels = {pid: state.panels[pid] for pid in grid.panes if pid in state.panels}
    if not panels:
        return state
    return dataclasses.replace(state, grid=grid, panels=panels)


def turn_deck_layout(state: DeckAreaState) -> DeckAreaState:
    """Transpose the split (stacked/side-by-side); inert unless split."""
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    return dataclasses.replace(state, grid=turn(state.grid))


def step_ratio(state: DeckAreaState, grow: bool) -> DeckAreaState:
    """Step the focused pane's share through ``RATIO_STEPS``.

    Grow means the focused pane gets bigger. Clamps at the ends.
    Disabled while zoomed.
    """
    if state.zoom_snapshot is not None:
        return state
    if len(state.grid.panes) < 2:
        return state
    return dataclasses.replace(state, grid=pane_grid.step_ratio(state.grid, grow))
