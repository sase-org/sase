"""Deck split layout actions for the Agents tab."""

from __future__ import annotations


class AgentDeckLayoutActionsMixin:
    """Actions toggling deck splits, focus and ratio."""

    current_tab: str

    def _deck_layout_detail(self) -> object | None:
        """Return the AgentDetail widget or None."""
        try:
            from ...widgets import AgentDetail

            return self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _decks_layout_active(self) -> bool:
        """Return whether deck splits own Agents detail navigation."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        try:
            from ...widgets.decks.flag import agent_decks_active

            return bool(agent_decks_active(self))
        except Exception:
            return False

    def _deck_split_active(self) -> bool:
        """Return whether a split layout is active."""
        if not self._decks_layout_active():
            return False
        try:
            from ...widgets.decks.model import DeckLayout

            detail = self._deck_layout_detail()
            if detail is None:
                return False
            return detail.deck_layout is not DeckLayout.SINGLE  # type: ignore[attr-defined]
        except Exception:
            return False

    def _refresh_deck_footer(self) -> None:
        try:
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass

    def action_toggle_deck_split_below(self) -> None:
        """Toggle a top-bottom deck split."""
        if not self._decks_layout_active():
            return
        try:
            from ...widgets.decks.model import DeckLayout

            detail = self._deck_layout_detail()
            if detail is None:
                return
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)  # type: ignore[attr-defined]
        except Exception:
            return
        self._refresh_deck_footer()

    def action_toggle_deck_split_right(self) -> None:
        """Toggle a left-right deck split."""
        if not self._decks_layout_active():
            return
        try:
            from ...widgets.decks.model import DeckLayout

            detail = self._deck_layout_detail()
            if detail is None:
                return
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)  # type: ignore[attr-defined]
        except Exception:
            return
        self._refresh_deck_footer()

    def action_toggle_deck_focus(self) -> None:
        """Move focus to the other deck panel."""
        if not self._deck_split_active():
            return
        try:
            detail = self._deck_layout_detail()
            if detail is None:
                return
            detail.toggle_deck_focus()  # type: ignore[attr-defined]
        except Exception:
            return
        self._refresh_deck_footer()

    def action_grow_deck_panel(self) -> None:
        """Grow the focused deck panel one ratio step."""
        if not self._deck_split_active():
            return
        try:
            detail = self._deck_layout_detail()
            if detail is None:
                return
            detail.step_deck_ratio(True)  # type: ignore[attr-defined]
        except Exception:
            return
        self._refresh_deck_footer()

    def action_shrink_deck_panel(self) -> None:
        """Shrink the focused deck panel one ratio step."""
        if not self._deck_split_active():
            return
        try:
            detail = self._deck_layout_detail()
            if detail is None:
                return
            detail.step_deck_ratio(False)  # type: ignore[attr-defined]
        except Exception:
            return
        self._refresh_deck_footer()
