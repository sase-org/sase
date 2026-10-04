"""Deck showing, card stickiness, cycling, and picker for AgentDetail."""

from __future__ import annotations

import logging
from typing import Any

from .decks.main_document import MainDeckDocument
from .decks.model import DeckId

log = logging.getLogger(__name__)


class AgentDetailDeckShowMixin:
    """Mixin showing decks, sticking cards, cycling, and picking decks."""

    _main_deck_document: MainDeckDocument
    _current_agent: Any | None
    _current_attempt_number: int | None
    _agent_detail_generation: int

    def show_deck(self, panel_index: int, deck: DeckId) -> None:
        """Show ``deck`` on ``panel_index`` and load it for the current subject."""
        area = self.deck_area  # type: ignore[attr-defined]
        try:
            siblings = [
                p
                for p in area.visible_panels()
                if p.deck is deck and p.panel_index != panel_index
            ]
        except Exception:
            siblings = []
        is_duplicate = bool(siblings)
        area.set_panel_deck(panel_index, deck)
        panel = area.panel(panel_index)
        agent = self._current_agent
        attempt_number = self._current_attempt_number
        if agent is None:
            try:
                panel.refresh_chrome()
            except Exception:
                pass
            return
        if deck is DeckId.MAIN:
            try:
                preferred = area.state.panels[panel_index].preferred_card_for(deck)
            except Exception:
                preferred = None
            try:
                panel.show_main_document(
                    self._main_deck_document, preferred_card=preferred
                )
            except Exception:
                pass
        elif deck is DeckId.FILES:
            if is_duplicate:
                try:
                    loader = getattr(self, "_load_files_panel_from_cache", None)
                    if callable(loader) and loader(panel, agent):
                        self._deck_refresh_availability()  # type: ignore[attr-defined]
                        try:
                            panel.refresh_chrome()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
            from ._agent_detail_files import load_deck_file_view

            try:
                load_deck_file_view(
                    panel.file_view,
                    agent,
                    attempt_number=attempt_number,
                    stale_threshold_seconds=10,
                )
            except Exception:
                pass
        elif deck is DeckId.TOOLS:
            if is_duplicate:
                try:
                    loader = getattr(self, "_load_tools_panel_from_cache", None)
                    if callable(loader) and loader(panel, agent):
                        self._deck_refresh_availability()  # type: ignore[attr-defined]
                        try:
                            panel.refresh_chrome()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
            from ..llm_calls import supports_slow_tool_sources

            try:
                if (
                    attempt_number is None
                    and not agent.is_clan_container
                    and not agent.is_named_proc
                    and supports_slow_tool_sources(agent)
                ):
                    panel.tools_view.update_display(agent)
                else:
                    panel.tools_view.show_empty()
            except Exception:
                pass
        elif deck is DeckId.FINAL:
            try:
                preferred = self._final_preferred_card(panel)  # type: ignore[attr-defined]
            except Exception:
                preferred = None
            try:
                panel.final_view.update_display(
                    agent,
                    attempt_number=attempt_number,
                    generation=self._agent_detail_generation,
                    preferred_card=preferred,
                )
            except Exception:
                pass
        else:
            log.warning("Unknown deck %r in show_deck; falling back to Main", deck)
            self.show_deck(panel_index, DeckId.MAIN)
            return
        self._deck_refresh_availability()  # type: ignore[attr-defined]
        try:
            panel.refresh_chrome()
        except Exception:
            pass
        try:
            self._notify_deck_state_changed()  # type: ignore[attr-defined]
        except Exception:
            pass

    def set_deck_preferred_card(
        self,
        panel_index: int,
        card_id: str | None,
        deck: DeckId | None = None,
    ) -> None:
        """Delegate preferred-card updates to the deck area.

        The card sticks under ``deck`` (default: the panel's own deck) so
        each deck keeps its own sticky card.
        """
        try:
            self.deck_area.set_preferred_card(panel_index, card_id, deck)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self._notify_deck_state_changed()  # type: ignore[attr-defined]
        except Exception:
            pass

    def cycle_focused_deck_card(self, direction: int) -> str | None:
        """Cycle cards in the focused panel; the shown deck's choice sticks."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panel = area.focused_panel()
        except Exception:
            return None
        try:
            shown = panel.cycle_card(direction)
        except Exception:
            return None
        if shown is not None:
            try:
                index = panel.panel_index
            except Exception:
                return shown
            try:
                deck = panel.deck
            except Exception:
                deck = None
            if deck is DeckId.TOOLS:
                self._remember_deck_preferred_card(index, shown, DeckId.TOOLS)
            else:
                self.set_deck_preferred_card(index, shown)
        return shown

    def _remember_deck_preferred_card(
        self,
        panel_index: int,
        card_id: str | None,
        deck: DeckId | None = None,
    ) -> None:
        """Record the preferred card without re-showing the Main document.

        Block-only swaps already show the owning card; only the stickiness
        record needs updating so later subjects land on this card. The card
        sticks under ``deck`` (default: the panel's own deck).
        """
        try:
            self.deck_area.set_preferred_card_state(panel_index, card_id, deck)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self._notify_deck_state_changed()  # type: ignore[attr-defined]
        except Exception:
            pass

    def cycle_focused_card_block(self, direction: int) -> bool:
        """Cycle card blocks in the focused panel; the owning card sticks."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panel = area.focused_panel()
        except Exception:
            return False
        try:
            moved = panel.cycle_block(direction)
        except Exception:
            return False
        if not moved:
            return False
        try:
            index = panel.panel_index
        except Exception:
            return True
        try:
            active = panel.active_deck_card()
        except Exception:
            try:
                active = panel.active_main_card()
            except Exception:
                active = None
        self._remember_deck_preferred_card(index, active)
        return True

    def select_focused_card_block(self, block_id: str | None) -> bool:
        """Select a card block in the focused panel; the owning card sticks."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panel = area.focused_panel()
        except Exception:
            return False
        try:
            moved = panel.select_block(block_id)
        except Exception:
            return False
        if not moved:
            return False
        try:
            index = panel.panel_index
        except Exception:
            return True
        try:
            active = panel.active_deck_card()
        except Exception:
            try:
                active = panel.active_main_card()
            except Exception:
                active = None
        self._remember_deck_preferred_card(index, active)
        return True

    def cycle_focused_deck(self, direction: int) -> None:
        """Cycle the focused panel to the next/previous deck (wraps)."""
        from .decks.model import cycle_deck_id

        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panel = area.focused_panel()
            index = panel.panel_index
        except Exception:
            return
        try:
            self.show_deck(index, cycle_deck_id(panel.deck, direction))
        except Exception:
            pass

    def deck_picker_state(self) -> Any | None:
        """Snapshot the focused panel for the deck picker, or None."""
        from .decks.layout import is_zoomed
        from .decks.picker import (
            DeckPickerState,
            other_panel_target,
            panel_position_label,
        )

        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
            focused = area.focused_panel()
            panel_index = focused.panel_index
            current = focused.deck
            availability = dict(focused.availability)
            accents = dict(focused.deck_accents())
            panel_label = panel_position_label(state, panel_index)
            other: tuple[DeckId, str] | None = None
            if not is_zoomed(state):
                try:
                    visible = area.visible_panels()
                except Exception:
                    visible = ()
                if len(visible) > 1:
                    for candidate in visible:
                        try:
                            candidate_index = candidate.panel_index
                        except Exception:
                            continue
                        if candidate_index != panel_index:
                            try:
                                other = (
                                    candidate.deck,
                                    panel_position_label(state, candidate_index),
                                )
                            except Exception:
                                other = None
                            break
            try:
                previous = state.panels[panel_index].previous_deck
            except Exception:
                previous = None
            opener_display = "p"
            try:
                from ..keymaps import key_display_name, split_key_alternatives
                from ..keymaps.key_validation import is_unbound_key

                registry = getattr(self.app, "_keymap_registry", None)  # type: ignore[attr-defined]
                configured = getattr(getattr(registry, "app", None), "pick_deck", "")
                raw = str(configured) if configured else ""
                alts = tuple(
                    k
                    for k in split_key_alternatives(raw)
                    if k and not is_unbound_key(k)
                )
                opener_display = key_display_name(alts[0]) if alts else ""
            except Exception:
                opener_display = "p"
            return DeckPickerState(
                panel_index=panel_index,
                panel_label=panel_label,
                current=current,
                other=other,
                availability=availability,
                accents=accents,
                other_target=other_panel_target(state, panel_index),
                previous=previous,
                opener_display=opener_display,
            )
        except Exception:
            return None

    def apply_picked_deck(self, panel_index: int | None, deck: DeckId) -> bool:
        """Show ``deck`` on the resolved panel; False when already showing."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
        except Exception:
            return False
        try:
            visible_indices = {p.panel_index for p in area.visible_panels()}
        except Exception:
            visible_indices = set()
        try:
            focused_index = area.focused_panel().panel_index
        except Exception:
            return False
        if panel_index is not None and panel_index in visible_indices:
            index = panel_index
        else:
            index = focused_index
        try:
            if area.panel(index).deck is deck:
                return False
        except Exception:
            return False
        try:
            self.show_deck(index, deck)
        except Exception:
            return False
        return True


__all__ = ["AgentDetailDeckShowMixin"]
