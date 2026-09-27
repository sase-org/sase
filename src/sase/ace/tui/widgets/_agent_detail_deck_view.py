"""Focused-panel deck-view cycle API for AgentDetail."""

from __future__ import annotations

from typing import Any

from .decks.model import DeckId, DeckView


class AgentDetailDeckViewMixin:
    """Mixin providing the focused-panel deck-view cycle and set actions."""

    def _focused_view_panel(self) -> tuple[Any, int]:
        """Return the focused deck panel and its index."""
        area = self.deck_area  # type: ignore[attr-defined]
        try:
            panel = area.focused_panel()
        except Exception:
            panel = area.panel(0)
        try:
            index = int(panel.panel_index)
        except Exception:
            index = 0
        return panel, index

    def cycle_focused_deck_view(self) -> tuple[DeckView, bool] | None:
        """Cycle the focused panel's deck view one step wider.

        Returns the new fixed view and whether the press fixed an AUTO
        policy (for the one-time teaching toast), or ``None`` when the
        cycle is unavailable.
        """
        try:
            panel, index = self._focused_view_panel()
        except Exception:
            return None
        try:
            deck = panel.deck
        except Exception:
            return None
        if deck not in (DeckId.MAIN, DeckId.FILES):
            return None
        try:
            if not bool(panel.deck_view_cycle_available):
                return None
        except Exception:
            return None
        try:
            policy = panel.view_policy(deck)
        except Exception:
            return None
        first_fix = policy is DeckView.AUTO
        try:
            nxt = panel.next_view()
        except Exception:
            return None
        if nxt is None:
            return None
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.set_panel_view(index, deck, nxt)
        except Exception:
            return None
        try:
            self._notify_deck_state_changed()  # type: ignore[attr-defined]
        except Exception:
            pass
        return (nxt, first_fix)

    def set_focused_deck_view(self, view: DeckView) -> bool:
        """Set the focused panel's deck view; False when rejected."""
        try:
            panel, index = self._focused_view_panel()
        except Exception:
            return False
        try:
            deck = panel.deck
        except Exception:
            return False
        if deck not in (DeckId.MAIN, DeckId.FILES):
            return False
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.set_panel_view(index, deck, view)
        except Exception:
            return False
        try:
            self._notify_deck_state_changed()  # type: ignore[attr-defined]
        except Exception:
            pass
        return True


__all__ = ["AgentDetailDeckViewMixin"]
