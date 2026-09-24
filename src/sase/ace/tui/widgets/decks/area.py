"""Two pre-composed deck panels with a focused index."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical

from .model import (
    DeckAreaState,
    DeckId,
    SINGLE,
    with_panel_deck,
    with_preferred_card,
)
from .panel import DeckPanel


class DeckArea(Vertical):
    """Area holding two pre-composed deck panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the deck area."""
        super().__init__(**kwargs)
        self._state: DeckAreaState = DeckAreaState(
            panels=(
                DeckAreaState().panels[0],
                DeckAreaState().panels[0],
            ),
            focused=0,
        )
        # Ensure the default SINGLE shape is preserved for state helpers.
        _ = SINGLE

    @property
    def state(self) -> DeckAreaState:
        """Return the deck area state."""
        return self._state

    def compose(self) -> ComposeResult:
        """Compose both panels; panel 1 starts hidden."""
        yield DeckPanel(0, id="agent-deck-panel-0", classes="deck-panel")
        yield DeckPanel(1, id="agent-deck-panel-1", classes="deck-panel hidden")

    def panel(self, index: int) -> DeckPanel:
        """Return the panel at ``index``."""
        panels = self.query(DeckPanel)
        if index < 0 or index >= len(panels):
            raise IndexError(index)
        return panels[index]

    def visible_panels(self) -> tuple[DeckPanel, ...]:
        """Return the visible panels (panel 0 only in SINGLE)."""
        try:
            return (self.panel(0),)
        except Exception:
            return ()

    def focused_panel(self) -> DeckPanel:
        """Return the focused panel."""
        return self.panel(self._state.focused)

    def set_panel_deck(self, index: int, deck: DeckId) -> None:
        """Update state and the panel's deck."""
        self._state = with_panel_deck(self._state, index, deck)
        self.panel(index).set_deck(deck)

    def set_preferred_card(self, index: int, card_id: str | None) -> None:
        """Update preferred card and re-show the stored Main document."""
        self._state = with_preferred_card(self._state, index, card_id)
        panel = self.panel(index)
        try:
            document = panel._main_document
        except Exception:
            return
        try:
            panel.show_main_document(document, preferred_card=card_id)
        except Exception:
            pass

    def panels_showing(self, deck: DeckId) -> tuple[DeckPanel, ...]:
        """Return visible panels showing ``deck``."""
        return tuple(p for p in self.visible_panels() if p.deck is deck)
