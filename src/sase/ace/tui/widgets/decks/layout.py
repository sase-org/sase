"""Pure deck split layout transitions."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from .model import (
    DECK_CYCLE,
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
    cycle_card_id,
)

RATIO_STEPS: tuple[int, ...] = (30, 50, 70)


def choose_new_panel(
    current_deck: DeckId,
    current_active_card: str | None,
    shown: Sequence[DeckId] | set[DeckId] | frozenset[DeckId],
    has_content: Mapping[DeckId, bool | None],
    card_ids: Sequence[str],
) -> DeckPanelState:
    """Choose the deck for a newly opened panel.

    Walk ``DECK_CYCLE`` forward from ``current_deck`` and pick the first
    deck that is not in ``shown`` and whose ``has_content`` entry is not
    ``False``. Unknown (``None`` or missing) counts as content. When none
    qualifies, duplicate ``current_deck`` on the card after
    ``current_active_card``.
    """
    shown_set = set(shown)
    try:
        start = DECK_CYCLE.index(current_deck)
    except ValueError:
        start = -1
    for offset in range(1, len(DECK_CYCLE) + 1):
        candidate = DECK_CYCLE[(start + offset) % len(DECK_CYCLE)]
        if candidate in shown_set:
            continue
        try:
            content = has_content[candidate]
        except Exception:
            content = None
        if content is False:
            continue
        return DeckPanelState(candidate)
    if current_deck is DeckId.MAIN:
        preferred = cycle_card_id(tuple(card_ids), current_active_card, 1)
    else:
        preferred = None
    return DeckPanelState(current_deck, preferred)


def toggle_split(
    state: DeckAreaState,
    target: DeckLayout,
    new_panel: DeckPanelState,
) -> DeckAreaState:
    """Toggle a split layout for ``target``.

    From SINGLE open ``new_panel`` as panel 1 with focus and 50/50 ratio.
    Pressing the same layout key again unsplits back to panel 0. Pressing
    the other layout key rotates, keeping decks, cards, focus and ratio.
    """
    if state.layout is DeckLayout.SINGLE:
        return DeckAreaState(
            panels=(state.panels[0], new_panel),
            focused=1,
            layout=target,
            ratio=50,
        )
    if state.layout is target:
        return DeckAreaState(
            panels=(state.panels[0],),
            focused=0,
            layout=DeckLayout.SINGLE,
            ratio=50,
        )
    return dataclasses.replace(state, layout=target)


def toggle_focus(state: DeckAreaState) -> DeckAreaState:
    """Move logical focus to the other panel in a split."""
    if state.layout is DeckLayout.SINGLE:
        return state
    return dataclasses.replace(state, focused=1 - state.focused)


def step_ratio(state: DeckAreaState, grow: bool) -> DeckAreaState:
    """Step the first panel's share through ``RATIO_STEPS``.

    Grow means the focused panel gets bigger. Clamps at the ends.
    """
    if state.layout is DeckLayout.SINGLE:
        return state
    try:
        index = RATIO_STEPS.index(state.ratio)
    except ValueError:
        index = 1
    if state.focused == 0:
        index = index + 1 if grow else index - 1
    else:
        index = index - 1 if grow else index + 1
    index = max(0, min(len(RATIO_STEPS) - 1, index))
    return dataclasses.replace(state, ratio=RATIO_STEPS[index])
