"""Pure deck-panel state model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Sequence


class DeckId(StrEnum):
    """Agent data deck identifier."""

    MAIN = "main"
    FILES = "files"
    TOOLS = "tools"


DECK_CYCLE: tuple[DeckId, ...] = (DeckId.MAIN, DeckId.FILES, DeckId.TOOLS)


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


SINGLE: DeckAreaState = DeckAreaState()


def with_panel_deck(state: DeckAreaState, index: int, deck: DeckId) -> DeckAreaState:
    """Return a new state with ``index`` showing ``deck``."""
    panels = list(state.panels)
    if index < 0 or index >= len(panels):
        raise IndexError(index)
    current = panels[index]
    panels[index] = DeckPanelState(deck, current.preferred_card)
    return DeckAreaState(panels=tuple(panels), focused=state.focused)


def with_preferred_card(
    state: DeckAreaState, index: int, card_id: str | None
) -> DeckAreaState:
    """Return a new state with ``index`` preferring ``card_id``."""
    panels = list(state.panels)
    if index < 0 or index >= len(panels):
        raise IndexError(index)
    current = panels[index]
    panels[index] = DeckPanelState(current.deck, card_id)
    return DeckAreaState(panels=tuple(panels), focused=state.focused)


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
