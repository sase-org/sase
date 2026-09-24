"""Pre-composed deck panel with Main, Files and Tools views."""

from __future__ import annotations

from typing import Any

from rich.text import Text
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
from .empty_state import deck_empty_state
from .main_document import EMPTY_MAIN_DOCUMENT, MainDeckDocument
from .main_view import MainDeckView
from .model import DeckId, cycle_card_id
from .titles import (
    CardTab,
    deck_subtitle,
    deck_title,
    file_line_status,
)

_DECK_ACCENT_CLASS = {
    DeckId.MAIN: "-deck-main",
    DeckId.FILES: "-deck-files",
    DeckId.TOOLS: "-deck-tools",
}

_FALLBACK_ACCENTS = {
    DeckId.MAIN: "#B48EAD",
    DeckId.FILES: "green",
    DeckId.TOOLS: "#87D7FF",
}


class DeckPanelFocusRequested(Message):
    """Request logical focus for a deck panel."""

    def __init__(self, panel_index: int) -> None:
        """Initialize the focus request."""
        super().__init__()
        self.panel_index = panel_index


class DeckPanel(Vertical):
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

    @property
    def panel_index(self) -> int:
        """Return the panel index."""
        return self._panel_index

    @property
    def deck(self) -> DeckId:
        """Return the active deck."""
        return self._deck

    def compose(self) -> ComposeResult:
        """Compose the pre-composed Main, Files and Tools scrolls."""
        i = self._panel_index
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-main-scroll", classes="deck-scroll -main"
        ):
            yield MainDeckView()
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-files-scroll", classes="deck-scroll -files"
        ):
            yield AgentFilePanel()
        with VerticalScroll(
            id=f"agent-deck-panel-{i}-tools-scroll", classes="deck-scroll -tools"
        ):
            yield AgentLLMCallsPanel()
        yield Static(classes="deck-empty-state")

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

    def on_click(self, event: object) -> None:
        """Request logical focus without stealing widget focus."""
        try:
            self.post_message(DeckPanelFocusRequested(self._panel_index))
        except Exception:
            pass

    def _resolve_accent(self, deck: DeckId) -> str:
        if deck is DeckId.MAIN:
            try:
                variables = self.app.theme_variables  # type: ignore[attr-defined]
                secondary = variables.get("secondary")
                if secondary:
                    return str(secondary)
            except Exception:
                pass
            return _FALLBACK_ACCENTS[DeckId.MAIN]
        return _FALLBACK_ACCENTS[deck]

    def _accent_for(self) -> dict[DeckId, str]:
        return {deck: self._resolve_accent(deck) for deck in DeckId}

    def _chrome_width(self) -> int:
        try:
            width = int(self.size.width)
        except Exception:
            width = 0
        return width if width > 0 else 80

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

    def _deck_switch_hint(self) -> str | None:
        """Return the live deck-switch hint for the empty-state card."""
        try:
            from ...keymaps import key_display_name
        except Exception:
            return None
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is not None:
                next_key = key_display_name(
                    str(getattr(getattr(registry, "app", None), "next_deck", ""))
                )
                prev_key = key_display_name(
                    str(getattr(getattr(registry, "app", None), "prev_deck", ""))
                )
            else:
                next_key = prev_key = ""
        except Exception:
            return None
        if not next_key or not prev_key:
            return None
        return f"{next_key} next deck · {prev_key} previous deck"

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

    def cycle_card(self, direction: int) -> str | None:
        """Cycle cards in the active deck; return the new Main card id."""
        if self._deck is DeckId.MAIN:
            ids = [card.card_id for card in self._main_document.cards]
            try:
                active = self.main_view.active_card_id
            except Exception:
                active = self._main_active_card
            next_id = cycle_card_id(ids, active, direction)
            if next_id is None:
                return None
            try:
                shown = self.main_view.show_card(next_id)
            except Exception:
                return None
            if shown is None:
                return None
            self._main_active_card = shown
            self.refresh_chrome()
            return shown
        if self._deck is DeckId.FILES:
            try:
                view = self.file_view
                if direction >= 0:
                    view.next_file()
                else:
                    view.prev_file()
            except Exception:
                pass
            try:
                self.refresh_chrome()
            except Exception:
                pass
            return None
        return None

    def show_main_document(
        self, document: MainDeckDocument, preferred_card: str | None
    ) -> str | None:
        """Push ``document`` to the Main view; return the active card."""
        self._main_document = document
        try:
            active = self.main_view.show_document(
                document, preferred_card=preferred_card
            )
        except Exception:
            active = None
        self._main_active_card = active
        if self._deck is DeckId.MAIN:
            self.set_deck(DeckId.MAIN)
        else:
            self.refresh_chrome()
        return active

    @property
    def main_view(self) -> MainDeckView:
        """Return the Main deck view."""
        return self.query_one(MainDeckView)

    @property
    def file_view(self) -> AgentFilePanel:
        """Return the Files deck view."""
        return self.query_one(AgentFilePanel)

    @property
    def tools_view(self) -> AgentLLMCallsPanel:
        """Return the Tools deck view."""
        return self.query_one(AgentLLMCallsPanel)

    def active_scroll(self) -> VerticalScroll:
        """Return the displayed scroll container."""
        return self.query_one(
            f"#agent-deck-panel-{self._panel_index}-{self._deck.value}-scroll",
            VerticalScroll,
        )

    def set_availability(self, availability: dict[DeckId, DeckAvailability]) -> None:
        """Store availability probes and refresh chrome."""
        self._availability = dict(availability)
        if self._deck is not DeckId.MAIN:
            self.set_deck(self._deck)
        else:
            self.refresh_chrome()

    def _main_tabs(self) -> tuple[CardTab, ...]:
        tabs: list[CardTab] = []
        for card in self._main_document.cards:
            tabs.append(CardTab(card.card_id, card.title))
        return tuple(tabs)

    def _files_tabs(self) -> tuple[CardTab, ...]:
        try:
            view = self.file_view
            file_list = list(getattr(view, "_file_list", []))
            index = int(getattr(view, "_current_file_index", 0))
        except Exception:
            return ()
        tabs: list[CardTab] = []
        for i, _page in enumerate(file_list):
            label = f"file {i + 1}"
            if i == index:
                try:
                    current = view.current_source_label()
                except Exception:
                    current = None
                if current:
                    label = current
            tabs.append(CardTab(f"file-{i}", label))
        return tuple(tabs)

    def _active_tab_index(self) -> int | None:
        if self._deck is DeckId.MAIN:
            ids = [card.card_id for card in self._main_document.cards]
            if self._main_active_card is None:
                return None if not ids else None
            try:
                return ids.index(self._main_active_card)
            except ValueError:
                return None
        if self._deck is DeckId.FILES:
            try:
                view = self.file_view
                if not getattr(view, "_file_list", []):
                    return None
                return int(getattr(view, "_current_file_index", 0))
            except Exception:
                return None
        return 0

    def refresh_chrome(self) -> None:
        """Recompute the border title and subtitle."""
        width = self._chrome_width()
        accent_for = self._accent_for()
        accent = accent_for[self._deck]
        if self._deck is DeckId.MAIN:
            tabs = self._main_tabs()
        elif self._deck is DeckId.FILES:
            tabs = self._files_tabs()
        else:
            tabs = (CardTab("llm-calls", "LLM Calls"),)
        active_index = self._active_tab_index()
        if self._deck is DeckId.MAIN and not tabs:
            active_index = None
        try:
            self.border_title = deck_title(
                self._deck,
                tabs,
                active_index,
                width=width,
                accent=accent,
                focused=self._focused,
            )
        except Exception:
            pass
        if self._deck is DeckId.FILES:
            status = file_line_status(
                self._file_visible_lines,
                self._file_total_lines,
                self._file_capped,
                editor_key="E",
            )
        else:
            status = None
        try:
            self.border_subtitle = deck_subtitle(
                self._deck,
                self._availability,
                status=status,
                width=width,
                accent_for=accent_for,
            )
        except Exception:
            pass

    def on_resize(self, event: object) -> None:
        """Recompute the title tier on resize."""
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

    def _notify_duplicate_ready(self, deck: DeckId) -> None:
        """Ask AgentDetail to re-feed sibling duplicates from cache."""
        try:
            node: object | None = self.parent
            for _ in range(5):
                if node is None:
                    break
                reload = getattr(node, "_reload_duplicate_deck_from_cache", None)
                if callable(reload):
                    try:
                        reload(deck, exclude_panel_index=self._panel_index)
                    except Exception:
                        pass
                    break
                node = getattr(node, "parent", None)
        except Exception:
            pass

    @on(FileListChanged)
    def _on_deck_file_list_changed(self, message: FileListChanged) -> None:
        self._file_count = message.file_count
        self._file_index = message.file_index
        try:
            self._file_source_label = self.file_view.current_source_label()
        except Exception:
            self._file_source_label = None
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.FILES)
        message.stop()

    @on(FileLineCountChanged)
    def _on_deck_file_line_count_changed(self, message: FileLineCountChanged) -> None:
        self._file_visible_lines = message.visible_lines
        self._file_total_lines = message.total_lines
        self._file_capped = message.capped
        self.refresh_chrome()
        message.stop()

    @on(FileVisibilityChanged)
    def _on_deck_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        self._availability[DeckId.FILES] = DeckAvailability(
            bool(message.has_file), message.file_count
        )
        self._file_count = message.file_count
        self._file_index = message.file_index
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.FILES)
        message.stop()

    @on(LLMCallsVisibilityChanged)
    def _on_deck_llm_calls_visibility_changed(
        self, message: LLMCallsVisibilityChanged
    ) -> None:
        self._tools_has_content = bool(message.has_llm_calls)
        self._availability[DeckId.TOOLS] = DeckAvailability(
            bool(message.has_llm_calls), None
        )
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.TOOLS)
        message.stop()
