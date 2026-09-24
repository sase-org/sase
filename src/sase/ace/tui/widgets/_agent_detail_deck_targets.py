"""Deck-target resolvers for AgentDetail (deck-action-retarget)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .decks.model import DeckId as _DeckId
    from .decks.panel import DeckPanel as _DeckPanel
    from .decks.main_view import MainDeckView as _MainDeckView
    from .file_panel import AgentFilePanel as _AgentFilePanel
    from .llm_calls_panel import AgentLLMCallsPanel as _AgentLLMCallsPanel


class AgentDetailDeckTargetsMixin:
    """Pure deck lookups over ``deck_area`` for key actions and clipboard."""

    def focused_deck(self) -> Any | None:
        """Return the focused panel's deck, or None with the flag off."""
        if not bool(getattr(self, "decks_enabled", False)):
            return None
        try:
            return self.deck_area.focused_panel().deck  # type: ignore[attr-defined]
        except Exception:
            return None

    def focused_file_view(self) -> Any | None:
        """Return the Files view key actions and clipboard target."""
        if not bool(getattr(self, "decks_enabled", False)):
            return None
        try:
            from .decks.model import DeckId

            area = self.deck_area  # type: ignore[attr-defined]
            focused = area.focused_panel()
            if focused.deck is DeckId.FILES:
                return focused.file_view
            for panel in area.visible_panels():
                if panel.deck is DeckId.FILES:
                    return panel.file_view
        except Exception:
            return None
        return None

    def focused_tools_view(self) -> Any | None:
        """Return the Tools view only when the focused deck is Tools."""
        if not bool(getattr(self, "decks_enabled", False)):
            return None
        try:
            from .decks.model import DeckId

            focused = self.deck_area.focused_panel()  # type: ignore[attr-defined]
            if focused.deck is DeckId.TOOLS:
                return focused.tools_view
        except Exception:
            return None
        return None

    def main_view_for_actions(self) -> tuple[Any, Any] | None:
        """Return the (panel, Main view) fold and E actions should use."""
        if not bool(getattr(self, "decks_enabled", False)):
            return None
        try:
            from .decks.model import DeckId

            area = self.deck_area  # type: ignore[attr-defined]
            focused = area.focused_panel()
            if focused.deck is DeckId.MAIN:
                return (focused, focused.main_view)
            for panel in area.visible_panels():
                if panel.deck is DeckId.MAIN:
                    return (panel, panel.main_view)
        except Exception:
            return None
        return None

    def ensure_main_deck_shown(self) -> None:
        """Show Main on the focused panel when no visible panel shows it."""
        if not bool(getattr(self, "decks_enabled", False)):
            return
        try:
            from .decks.model import DeckId

            area = self.deck_area  # type: ignore[attr-defined]
            for panel in area.visible_panels():
                if panel.deck is DeckId.MAIN:
                    return
            focused_index = int(area.state.focused)
            show = getattr(self, "show_deck", None)
            if callable(show):
                show(focused_index, DeckId.MAIN)
        except Exception:
            pass

    def reapply_main_view_pins(self) -> None:
        """Re-apply bottom pins on every visible Main view."""
        if not bool(getattr(self, "decks_enabled", False)):
            return
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            for deck_panel in area.visible_panels():
                try:
                    main_view = deck_panel.main_view
                except Exception:
                    continue
                if bool(getattr(main_view, "is_pinned_to_bottom", False)):
                    reschedule = getattr(
                        main_view, "_schedule_bottom_pin_reapply", None
                    )
                    if callable(reschedule):
                        reschedule()
        except Exception:
            pass


__all__ = ["AgentDetailDeckTargetsMixin"]
