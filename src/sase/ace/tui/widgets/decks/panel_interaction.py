"""Scroll tracking, view accessors, search overlay and resize for ``DeckPanel``.

Extracted from ``panel.py`` so the panel shell stays under the line-count
gate. All cross-mixin collaborators are reached through ``self``; this module
imports only public names and never a ``_``-prefixed symbol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from ..file_panel import AgentFilePanel
from ..llm_calls_panel import AgentLLMCallsPanel
from .availability import DeckAvailability
from .files_spread import FilesSpreadView
from .main_document import MainDeckDocument
from .main_view import MainDeckView
from .model import DeckId, RenderMode


class DeckPanelInteractionMixin:
    """Scroll, search, resize and deck-message handlers for a deck panel."""

    _panel_index: int
    _deck: DeckId
    _availability: dict[DeckId, DeckAvailability]
    _main_document: MainDeckDocument
    _main_active_card: str | None
    _file_index: int
    _file_source_label: str | None
    _resize_decision_pending: bool

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _watch_deck_scrolls(self) -> None:
        try:
            main_scroll = self.query_one(
                f"#agent-deck-panel-{self._panel_index}-main-scroll",
                VerticalScroll,
            )
            self.watch(main_scroll, "scroll_y", self._on_main_scroll_y, init=False)
        except Exception:
            pass
        try:
            files_scroll = self.query_one(
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            self.watch(files_scroll, "scroll_y", self._on_files_scroll_y, init=False)
        except Exception:
            pass

    def _on_main_scroll_y(self, _old: int, _new: int) -> None:
        if self._deck is not DeckId.MAIN:
            return
        spread = False
        try:
            spread = bool(self.is_spread(DeckId.MAIN))
        except Exception:
            spread = False
        if spread:
            try:
                derived = self._main_spread_active()
            except Exception:
                derived = None
            if derived is not None and derived != self._main_active_card:
                self._main_active_card = derived
                try:
                    self.refresh_chrome()
                except Exception:
                    pass
        # Scroll-derived block cursor for spread renderings (O(blocks) over
        # cached anchors; content growth does not move scroll_y, so streaming
        # never silently flips following).
        try:
            self._sync_spread_block_cursor_from_scroll()
        except Exception:
            pass

    def _sync_spread_block_cursor_from_scroll(self) -> None:
        """Recompute the spread block cursor from the scroll position."""
        try:
            from .flag import card_blocks_enabled

            if not card_blocks_enabled():
                return
        except Exception:
            return
        try:
            document = self._main_document
            if getattr(document, "partial", False):
                return
        except Exception:
            return
        try:
            view = self.main_view
        except Exception:
            return
        try:
            spread = bool(self.is_spread(DeckId.MAIN))
        except Exception:
            spread = False
        card = None
        try:
            if spread:
                try:
                    preferred = self._main_active_card
                except Exception:
                    preferred = None
                card = self._spread_block_card(document, preferred)  # type: ignore[attr-defined]
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = None
                if active is None:
                    try:
                        active = self._main_active_card
                    except Exception:
                        active = None
                if active is None:
                    return
                try:
                    block_mode = view.block_mode_for_active_card()
                except Exception:
                    block_mode = None
                if block_mode is not RenderMode.SPREAD:
                    return
                card = document.card(active)
                if card is None or not bool(card.has_block_navigation):
                    return
        except Exception:
            return
        if card is None:
            return
        try:
            updated = view.sync_spread_cursor_from_scroll(card)  # type: ignore[attr-defined]
        except Exception:
            updated = None
        if updated is None:
            return
        try:
            self.refresh_chrome()
        except Exception:
            pass
        try:
            self._sync_block_navigable()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_files_scroll_y(self, _old: int, _new: int) -> None:
        if not self.is_spread(DeckId.FILES) or self._deck is not DeckId.FILES:
            return
        try:
            index = self._files_spread_active_index()
            file_view = self.file_view
            current = int(getattr(file_view, "_current_file_index", 0))
            if index != current:
                try:
                    file_view.set_current_index_silent(index)
                except Exception:
                    pass
                self._file_index = index
                try:
                    self._file_source_label = file_view.current_source_label()
                except Exception:
                    pass
                try:
                    self.refresh_chrome()
                except Exception:
                    pass
        except Exception:
            pass

    @property
    def main_view(self) -> MainDeckView:
        """Return the Main deck view."""
        return self.query_one(MainDeckView)

    @property
    def file_view(self) -> AgentFilePanel:
        """Return the Files deck view."""
        return self.query_one(AgentFilePanel)

    @property
    def files_spread_view(self) -> FilesSpreadView:
        """Return the Files spread view."""
        return self.query_one(FilesSpreadView)

    @property
    def tools_view(self) -> AgentLLMCallsPanel:
        """Return the Tools deck view."""
        return self.query_one(AgentLLMCallsPanel)

    def active_main_card(self) -> str | None:
        """Return the active Main card id without reaching into privates."""
        try:
            return self.main_view.active_card_id
        except Exception:
            pass
        try:
            return self._main_active_card
        except Exception:
            return None

    def active_scroll(self) -> VerticalScroll:
        """Return the displayed scroll container."""
        return self.query_one(
            f"#agent-deck-panel-{self._panel_index}-{self._deck.value}-scroll",
            VerticalScroll,
        )

    def search_scroll(self) -> VerticalScroll:
        """Return the per-panel search overlay scroll."""
        return self.query_one(
            f"#agent-deck-panel-{self._panel_index}-search-scroll",
            VerticalScroll,
        )

    def search_panel(self) -> Static:
        """Return the per-panel search overlay content widget."""
        return self.query_one(
            f"#agent-deck-panel-{self._panel_index}-search-scroll .deck-search-panel",
            Static,
        )

    def search_command(self) -> Static:
        """Return the per-panel search command line widget."""
        return self.query_one(".deck-search-command", Static)

    def show_search_overlay(self) -> None:
        """Hide the active deck scroll and show the search overlay."""
        try:
            self.active_scroll().remove_class("-shown")
        except Exception:
            pass
        try:
            self.query_one(".deck-empty-state", Static).remove_class("-shown")
        except Exception:
            pass
        try:
            self.search_scroll().add_class("-shown")
        except Exception:
            pass
        try:
            self.search_panel().add_class("-shown")
            self.search_command().add_class("-shown")
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass

    def hide_search_overlay(self) -> None:
        """Hide the overlay and restore the active deck scroll."""
        try:
            self.search_scroll().remove_class("-shown")
        except Exception:
            pass
        try:
            self.search_panel().update("")
            self.search_panel().remove_class("-shown")
        except Exception:
            pass
        try:
            command = self.search_command()
            command.update("")
            command.border_title = ""
            command.border_subtitle = ""
            command.remove_class("-shown")
        except Exception:
            pass
        try:
            self.set_deck(self._deck)
        except Exception:
            pass

    def set_availability(self, availability: dict[DeckId, DeckAvailability]) -> None:
        """Store availability probes and refresh chrome."""
        self._availability = dict(availability)
        if self._deck is not DeckId.MAIN:
            self.set_deck(self._deck)
        else:
            self.refresh_chrome()

    def on_resize(self, event: object) -> None:
        """Recompute the title tier on resize and re-decide spread modes."""
        try:
            super().on_resize(event)  # type: ignore[misc]
        except Exception:
            pass
        self.refresh_chrome()
        if self._deck is DeckId.FILES:
            try:
                self.file_view.rerender_for_viewport()
            except Exception:
                pass
        if not self._resize_decision_pending:
            self._resize_decision_pending = True
            try:
                self.call_after_refresh(self._handle_resize_decision)
            except Exception:
                self._resize_decision_pending = False

    def _handle_resize_decision(self) -> None:
        self._resize_decision_pending = False
        try:
            if self._deck is DeckId.MAIN:
                self._refresh_main_mode_for_shown()
        except Exception:
            pass
        try:
            if self._deck is DeckId.MAIN:
                self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            if self._deck is DeckId.FILES:
                self._refresh_files_mode_for_shown()
        except Exception:
            pass


__all__ = ["DeckPanelInteractionMixin"]
