"""Pre-composed deck panel with Main, Files and Tools views."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ..file_panel import (
    AgentFilePanel,
    FileLineCountChanged,
    FileListChanged,
    FileVisibilityChanged,
)
from ..llm_calls_panel import AgentLLMCallsPanel, LLMCallsVisibilityChanged
from .availability import DeckAvailability
from .block_rail import BlockRail
from .empty_state import deck_empty_state
from .files_spread import FilesSpreadView
from .main_document import EMPTY_MAIN_DOCUMENT, MainDeckDocument
from .main_view import MainDeckView
from .model import DeckId
from .panel_blocks import DeckPanelBlocksMixin
from .panel_chrome import DeckPanelChromeMixin
from .panel_files import DeckPanelFilesMixin
from .panel_interaction import DeckPanelInteractionMixin
from .panel_navigation import DeckPanelNavigationMixin
from .panel_spread import DeckPanelSpreadMixin
from .panel_transitions import DeckPanelTransitionsMixin

_DECK_ACCENT_CLASS = {
    DeckId.MAIN: "-deck-main",
    DeckId.FILES: "-deck-files",
    DeckId.TOOLS: "-deck-tools",
}


class DeckPanelFocusRequested(Message):
    """Request logical focus for a deck panel."""

    def __init__(self, panel_index: int) -> None:
        """Initialize the focus request."""
        super().__init__()
        self.panel_index = panel_index


class DeckPanel(  # type: ignore[misc]
    DeckPanelBlocksMixin,
    DeckPanelChromeMixin,
    DeckPanelSpreadMixin,
    DeckPanelFilesMixin,
    DeckPanelTransitionsMixin,
    DeckPanelNavigationMixin,
    DeckPanelInteractionMixin,
    Vertical,
):
    """One pre-composed deck panel showing a single active deck."""

    def __init__(self, panel_index: int, **kwargs: Any) -> None:
        """Initialize the deck panel."""
        super().__init__(**kwargs)
        self._panel_index = panel_index
        self._deck = DeckId.MAIN
        self._id = f"agent-deck-panel-{panel_index}"
        self._focused = panel_index == 0
        self._availability: dict[DeckId, DeckAvailability] = {}
        self._main_document: MainDeckDocument = EMPTY_MAIN_DOCUMENT
        self._main_active_card: str | None = None
        self._file_count = 0
        self._file_index = 0
        self._file_source_label: str | None = None
        self._file_visible_lines = 0
        self._file_total_lines = 0
        self._file_capped = False
        self._tools_has_content = False
        self._init_spread_state()
        self._init_block_panel_state()

    @property
    def panel_index(self) -> int:
        """Return the panel index."""
        return self._panel_index

    @property
    def deck(self) -> DeckId:
        """Return the active deck."""
        return self._deck

    @property
    def availability(self) -> dict[DeckId, DeckAvailability]:
        """Return a copy of the deck availability probes."""
        return dict(self._availability)

    def deck_accents(self) -> dict[DeckId, str]:
        """Return the live accent for every deck."""
        return self._accent_for()

    def compose(self) -> ComposeResult:
        """Compose the pre-composed Main, Files and Tools scrolls."""
        i = self._panel_index
        yield BlockRail(classes="deck-block-rail")
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-main-scroll", classes="deck-scroll -main"
        ):
            yield MainDeckView()
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-files-scroll", classes="deck-scroll -files"
        ):
            yield AgentFilePanel()
            yield FilesSpreadView(classes="hidden")
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-tools-scroll", classes="deck-scroll -tools"
        ):
            yield AgentLLMCallsPanel()
        yield Static(classes="deck-empty-state")
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-search-scroll",
            classes="deck-scroll deck-search-scroll",
        ):
            yield Static(classes="deck-search-panel")
        yield Static(classes="deck-search-command")

    def on_mount(self) -> None:
        """Apply the initial deck chrome."""
        try:
            self.id = f"agent-deck-panel-{self._panel_index}"
        except Exception:
            pass
        self.set_deck(self._deck)
        try:
            self.set_focused(self._focused)
        except Exception:
            pass
        self._watch_deck_scrolls()
        self._sync_files_views()
        self._subscribe_theme_changes()

    def on_click(self, event: object) -> None:
        """Request logical focus without stealing widget focus."""
        try:
            self.post_message(DeckPanelFocusRequested(self._panel_index))
        except Exception:
            pass

    @on(BlockRail.BlockRailSelected)
    def _on_block_rail_selected(self, message: BlockRail.BlockRailSelected) -> None:
        """Select the rail-clicked block and take logical focus."""
        try:
            self.select_block(message.block_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.post_message(DeckPanelFocusRequested(self._panel_index))
        except Exception:
            pass

    def set_focused(self, focused: bool) -> None:
        """Sync focus chrome classes without moving widget focus."""
        self._focused = bool(focused)
        if self._focused:
            self.add_class("-focused")
            self.remove_class("-unfocused")
        else:
            self.add_class("-unfocused")
            self.remove_class("-focused")
        self.refresh_chrome()
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass

    def set_deck(self, deck: DeckId) -> None:
        """Show ``deck``, toggling scroll visibility and chrome."""
        self._deck = deck
        for existing in list(self.classes):
            if existing in ("-deck-main", "-deck-files", "-deck-tools"):
                self.remove_class(existing)
        self.add_class(_DECK_ACCENT_CLASS[deck])
        for deck_id in DeckId:
            try:
                scroll = self.query_one(
                    f"#agent-deck-panel-{self._panel_index}-{deck_id.value}-scroll",
                    VerticalScroll,
                )
            except Exception:
                continue
            if deck_id is deck and not self._deck_is_empty(deck):
                scroll.add_class("-shown")
            else:
                scroll.remove_class("-shown")
        self._update_empty_state()
        self.refresh_chrome()
        self._sync_files_views()
        # Switching to Main or Files re-decides with the current geometry.
        if deck is DeckId.MAIN:
            try:
                self._refresh_main_mode_for_shown()
            except Exception:
                pass
        elif deck is DeckId.FILES:
            try:
                self._refresh_files_mode_for_shown()
            except Exception:
                pass
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _deck_is_empty(self, deck: DeckId) -> bool:
        if deck is DeckId.MAIN:
            return not bool(self._main_document.cards)
        avail = self._availability.get(deck)
        if avail is not None:
            return not bool(avail.has_content)
        if deck is DeckId.FILES:
            try:
                return not bool(self.file_view._has_displayed_content)
            except Exception:
                return True
        try:
            return not bool(self.tools_view._has_displayed_content)
        except Exception:
            return True

    def _update_empty_state(self) -> None:
        try:
            empty = self.query_one(".deck-empty-state", Static)
        except Exception:
            return
        if self._deck_is_empty(self._deck):
            empty.add_class("-shown")
            try:
                empty.update(
                    deck_empty_state(
                        self._deck,
                        subject_kind="agent",
                        hint=self._deck_switch_hint(),
                    )
                )
            except Exception:
                pass
        else:
            empty.remove_class("-shown")

    def _sync_files_views(self) -> None:
        try:
            spread_view = self.files_spread_view
            file_view = self.file_view
        except Exception:
            return
        spread = self.is_spread(DeckId.FILES) and self._deck is DeckId.FILES
        try:
            if spread:
                file_view.add_class("hidden")
                spread_view.remove_class("hidden")
            else:
                spread_view.add_class("hidden")
                file_view.remove_class("hidden")
        except Exception:
            pass

    @on(FileListChanged)
    def _on_deck_file_list_changed(self, message: FileListChanged) -> None:
        self.handle_deck_file_list_changed(message)

    @on(FileLineCountChanged)
    def _on_deck_file_line_count_changed(self, message: FileLineCountChanged) -> None:
        self.handle_deck_file_line_count_changed(message)

    @on(FileVisibilityChanged)
    def _on_deck_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        self.handle_deck_file_visibility_changed(message)

    @on(LLMCallsVisibilityChanged)
    def _on_deck_llm_calls_visibility_changed(
        self, message: LLMCallsVisibilityChanged
    ) -> None:
        self.handle_deck_llm_calls_visibility_changed(message)


__all__ = ["DeckPanel", "DeckPanelFocusRequested"]
