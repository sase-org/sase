"""Pure deck-panel state model."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Sequence


class DeckId(StrEnum):
    """Agent data deck identifier."""

    MAIN = "main"
    FILES = "files"
    TOOLS = "tools"


DECK_CYCLE: tuple[DeckId, ...] = (DeckId.MAIN, DeckId.FILES, DeckId.TOOLS)


class DeckLayout(StrEnum):
    """Deck area split layout."""

    SINGLE = "single"
    TOP_BOTTOM = "top-bottom"
    LEFT_RIGHT = "left-right"


def cycle_deck_id(deck: DeckId, direction: int) -> DeckId:
    """Return the next deck in ``DECK_CYCLE`` for ``direction`` (wraps).

    Nothing is skipped: empty decks and decks shown in another panel are
    both visited so the order stays predictable.
    """
    index = DECK_CYCLE.index(deck)
    return DECK_CYCLE[(index + direction) % len(DECK_CYCLE)]


def cycle_card_id(
    card_ids: Sequence[str], active: str | None, direction: int
) -> str | None:
    """Return the next card id after ``active`` for ``direction`` (wraps)."""
    if not card_ids:
        return None
    if active is not None and active in card_ids:
        index = list(card_ids).index(active)
    else:
        # Unknown anchor: step from the default card so the keystroke still
        # moves by exactly one card from a sensible neighbor.
        default = default_card_id(card_ids)
        index = list(card_ids).index(default) if default is not None else -1
        if direction < 0:
            return list(card_ids)[index]
        return list(card_ids)[(index + 1) % len(card_ids)]
    return list(card_ids)[(index + direction) % len(card_ids)]


@dataclass(frozen=True)
class DeckPanelState:
    """One deck panel's deck and preferred Main card."""

    deck: DeckId
    preferred_card: str | None = None


@dataclass(frozen=True)
class DeckAreaState:
    """Pre-composed deck panels with a focused index."""

    panels: tuple[DeckPanelState, ...] = (DeckPanelState(DeckId.MAIN),)
    focused: int = 0
    layout: DeckLayout = DeckLayout.SINGLE
    ratio: int = 50


SINGLE: DeckAreaState = DeckAreaState()


def with_panel_deck(state: DeckAreaState, index: int, deck: DeckId) -> DeckAreaState:
    """Return a new state with ``index`` showing ``deck``."""
    panels = list(state.panels)
    if index < 0 or index >= len(panels):
        raise IndexError(index)
    current = panels[index]
    panels[index] = DeckPanelState(deck, current.preferred_card)
    return dataclasses.replace(state, panels=tuple(panels))


def with_preferred_card(
    state: DeckAreaState, index: int, card_id: str | None
) -> DeckAreaState:
    """Return a new state with ``index`` preferring ``card_id``."""
    panels = list(state.panels)
    if index < 0 or index >= len(panels):
        raise IndexError(index)
    current = panels[index]
    panels[index] = DeckPanelState(current.deck, card_id)
    return dataclasses.replace(state, panels=tuple(panels))


def default_card_id(card_ids: Sequence[str]) -> str | None:
    """Return the default card: Context, else first, else None."""
    if not card_ids:
        return None
    if "context" in card_ids:
        return "context"
    return card_ids[0]


def resolve_active_card(
    card_ids: Sequence[str],
    preferred: str | None,
    *,
    partial: bool,
) -> str | None:
    """Resolve the active card for a Main document paint."""
    if preferred is not None and preferred in card_ids:
        return preferred
    if partial and preferred is not None:
        return None
    return default_card_id(card_ids)
