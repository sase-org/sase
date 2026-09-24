"""Deck split layout API for AgentDetail."""

from __future__ import annotations

from typing import Any

from .decks.layout import choose_new_panel, step_ratio, toggle_focus, toggle_split
from .decks.model import DeckId, DeckLayout


class AgentDetailDeckLayoutMixin:
    """Mixin providing deck split, focus and ratio actions."""

    _main_deck_document: Any
    _current_agent: Any | None
    _current_attempt_number: int | None

    @property
    def deck_layout(self) -> DeckLayout:
        """Return the current deck split layout."""
        try:
            return self.deck_area.state.layout  # type: ignore[attr-defined]
        except Exception:
            return DeckLayout.SINGLE

    def toggle_deck_split(self, target: DeckLayout) -> None:
        """Toggle a deck split layout for ``target``."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return
        was_single = state.layout is DeckLayout.SINGLE
        if was_single:
            try:
                panel0 = area.panel(0)
                current_deck = panel0.deck
            except Exception:
                return
            try:
                if current_deck is DeckId.MAIN:
                    try:
                        active = panel0.main_view.active_card_id
                    except Exception:
                        active = getattr(panel0, "_main_active_card", None)
                    try:
                        card_ids = tuple(self._main_deck_document.card_ids)
                    except Exception:
                        card_ids = ()
                else:
                    active = None
                    card_ids = ()
            except Exception:
                active = None
                card_ids = ()
            try:
                shown = {p.deck for p in area.visible_panels()}
            except Exception:
                shown = {current_deck}
            try:
                raw_avail = dict(getattr(panel0, "_availability", {}))
                has_content = {
                    deck: (raw_avail[deck].has_content if deck in raw_avail else None)
                    for deck in (DeckId.MAIN, DeckId.FILES, DeckId.TOOLS)
                }
            except Exception:
                has_content = {}
            try:
                new_panel = choose_new_panel(
                    current_deck, active, shown, has_content, card_ids
                )
            except Exception:
                return
            is_duplicate_files = (
                current_deck is DeckId.FILES and new_panel.deck is DeckId.FILES
            )
            try:
                area.apply_state(toggle_split(state, target, new_panel))
            except Exception:
                return
            try:
                self.show_deck(1, new_panel.deck)  # type: ignore[attr-defined]
            except Exception:
                pass
            if is_duplicate_files:
                try:
                    panel1 = area.panel(1)
                    file_list = list(getattr(panel1.file_view, "_file_list", []))
                    if len(file_list) > 1:
                        panel1.file_view.next_file()
                except Exception:
                    pass
            try:
                self._deck_refresh_availability()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        try:
            area.apply_state(toggle_split(state, target, state.panels[-1]))
        except Exception:
            return

    def toggle_deck_focus(self) -> None:
        """Move logical focus to the other panel in a split."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(toggle_focus(area.state))
        except Exception:
            return

    def step_deck_ratio(self, grow: bool) -> None:
        """Grow or shrink the focused panel one ratio step."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(step_ratio(area.state, grow))
        except Exception:
            return

    def _reload_duplicate_deck_from_cache(
        self, deck: DeckId, exclude_panel_index: int | None = None
    ) -> None:
        """Re-feed duplicate ``deck`` panels from shared caches only."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            agent = self._current_agent
        except Exception:
            return
        if agent is None:
            return
        try:
            panels = area.visible_panels()
        except Exception:
            return
        for panel in panels:
            try:
                if panel.deck is not deck:
                    continue
                if (
                    exclude_panel_index is not None
                    and panel.panel_index == exclude_panel_index
                ):
                    continue
            except Exception:
                continue
            try:
                if deck is DeckId.FILES:
                    self._load_files_panel_from_cache(panel, agent)  # type: ignore[attr-defined]
                elif deck is DeckId.TOOLS:
                    self._load_tools_panel_from_cache(panel, agent)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _load_files_panel_from_cache(self, panel: Any, agent: Any) -> bool:
        """Load a Files view from cache without starting a diff worker."""
        try:
            from .file_panel._messages import (
                _LIVE_DIFF_SENTINEL,
                file_cache,
                get_cache_key,
            )
        except Exception:
            return False
        try:
            panel.file_view._reconcile_file_list(agent, allow_initial_display=True)
        except Exception:
            pass
        try:
            cache_key = get_cache_key(agent)
            entry = file_cache.get(cache_key)
        except Exception:
            entry = None
        if entry is None or entry.diff_output is None:
            try:
                panel.refresh_chrome()
            except Exception:
                pass
            return False
        try:
            file_list = list(getattr(panel.file_view, "_file_list", []))
            index = int(getattr(panel.file_view, "_current_file_index", 0))
            if file_list and file_list[index] != _LIVE_DIFF_SENTINEL:
                try:
                    panel.refresh_chrome()
                except Exception:
                    pass
                return True
        except Exception:
            pass
        try:
            panel.file_view._display_file_with_timestamp(
                entry.diff_output,
                entry.fetch_time,
                post_visibility_message=False,
            )
        except Exception:
            return False
        try:
            panel.refresh_chrome()
        except Exception:
            pass
        return True

    def _load_tools_panel_from_cache(self, panel: Any, agent: Any) -> bool:
        """Load a Tools view from cache without starting a fetch worker."""
        try:
            result = panel.tools_view._cached_fetch_result(agent)
        except Exception:
            return False
        if result is None:
            return False
        try:
            panel.tools_view._display_llm_calls_result(
                result, post_visibility_message=False
            )
        except Exception:
            return False
        try:
            panel.refresh_chrome()
        except Exception:
            pass
        return True
