"""Stopped-agent Context landing for AgentDetail's Main deck."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sase.ace.tui.util.pane_grid import focus_pane

from .decks.card_part import CONTEXT_CARD_ID
from .decks.model import DeckId


@dataclass
class _MainContextLanding:
    """One pending, in-memory request to land a stopped agent on Context."""

    identity: tuple[object, ...]
    pane_id: int
    landed: bool = False


class AgentDetailContextLandingMixin:
    """Focus Main and land a selected agent's complete document on Context."""

    _main_context_landing: _MainContextLanding | None
    _current_agent: Any | None
    _current_tribe_identity: Any | None

    def request_main_context_landing(self, identity: tuple[object, ...]) -> None:
        """Request a sticky Context landing for ``identity``."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
            focused_index = state.focused
            focused_panel = area.panel(focused_index)
        except Exception:
            return

        pane_id = focused_index
        if focused_panel.deck is not DeckId.MAIN:
            try:
                main_panels = tuple(area.panels_showing(DeckId.MAIN))
            except Exception:
                main_panels = ()
            if main_panels:
                recent = tuple(state.grid.recent)
                ordered = sorted(
                    main_panels,
                    key=lambda panel: (
                        recent.index(panel.panel_index)
                        if panel.panel_index in recent
                        else len(recent)
                    ),
                )
                pane_id = ordered[0].panel_index
                if pane_id != focused_index:
                    try:
                        self._apply_deck_area_state(  # type: ignore[attr-defined]
                            replace(state, grid=focus_pane(state.grid, pane_id))
                        )
                    except Exception:
                        return
                    self._notify_deck_state_changed()  # type: ignore[attr-defined]
            else:
                try:
                    self.show_deck(focused_index, DeckId.MAIN)  # type: ignore[attr-defined]
                except Exception:
                    return
                self._notify_deck_state_changed()  # type: ignore[attr-defined]

        try:
            self.set_deck_preferred_card(  # type: ignore[attr-defined]
                pane_id, CONTEXT_CARD_ID, DeckId.MAIN
            )
        except Exception:
            pass
        self._main_context_landing = _MainContextLanding(identity, pane_id)
        self._maybe_apply_main_context_landing()

    def _main_context_landing_matches(self) -> bool:
        """Return whether the pending request still names the selected agent."""
        request = self._main_context_landing
        if request is None:
            return False
        try:
            return (
                self._current_tribe_identity is None
                and self._current_agent is not None
                and self._current_agent.identity == request.identity
            )
        except Exception:
            return False

    def _maybe_apply_main_context_landing(self) -> None:
        """Apply the request once its target's complete Main document is visible."""
        request = self._main_context_landing
        if (
            request is None
            or request.landed
            or not self._main_context_landing_matches()
        ):
            return
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            visible_ids = {panel.panel_index for panel in area.visible_panels()}
            if request.pane_id not in visible_ids:
                return
            panel = area.panel(request.pane_id)
            if panel.deck is not DeckId.MAIN:
                return
            document = panel._main_document
            if document.partial or document.subject != self.metadata_identity:  # type: ignore[attr-defined]
                return
            if document.card(CONTEXT_CARD_ID) is not None:
                card_id = CONTEXT_CARD_ID
            elif document.cards:
                card_id = document.cards[0].card_id
            else:
                return
        except Exception:
            return
        try:
            landed = panel.land_main_card_top(card_id)
        except Exception:
            landed = None
        if landed is not None:
            request.landed = True

    def _clear_main_context_landing(self) -> None:
        """Drop the pending one-shot landing request."""
        self._main_context_landing = None


__all__ = ["AgentDetailContextLandingMixin"]
