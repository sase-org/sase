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
from .empty_state import deck_empty_state
from .files_spread import FilesSpreadView
from .main_document import EMPTY_MAIN_DOCUMENT, MainDeckDocument
from .main_view import MainDeckView
from .model import DeckId, RenderMode, cycle_card_id
from .panel_blocks import DeckPanelBlocksMixin
from .panel_chrome import DeckPanelChromeMixin
from .panel_files import DeckPanelFilesMixin
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

    def on_click(self, event: object) -> None:
        """Request logical focus without stealing widget focus."""
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

    def cycle_card(self, direction: int) -> str | None:
        """Cycle cards in the active deck; return the new Main card id."""
        if self._deck is DeckId.MAIN:
            if self.is_spread(DeckId.MAIN):
                return self._cycle_main_spread(direction)
            ids = [card.card_id for card in self._main_document.cards]
            try:
                active = self.main_view.active_card_id
            except Exception:
                active = self._main_active_card
            next_id = cycle_card_id(ids, active, direction)
            if next_id is None:
                return None
            try:
                block_mode = self._block_mode_for_card(self._main_document, next_id)
            except Exception:
                block_mode = None
            try:
                try:
                    shown = self.main_view.show_card(next_id, block_mode=block_mode)
                except TypeError:
                    shown = self.main_view.show_card(next_id)
            except Exception:
                return None
            if shown is None:
                return None
            self._main_active_card = shown
            self.refresh_chrome()
            try:
                self._sync_block_navigable()
            except Exception:
                pass
            return shown
        if self._deck is DeckId.FILES:
            if self.is_spread(DeckId.FILES):
                self._cycle_files_spread(direction)
                return None
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
        previous_document = self._main_document
        self._main_document = document
        # Partial documents never decide the mode.
        if document.partial:
            current = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
            try:
                active = self.main_view.show_document(
                    document, preferred_card=preferred_card, mode=current
                )
            except TypeError:
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
            try:
                self._sync_block_navigable()
            except Exception:
                pass
            return active
        stored_subject = self._mode_subject.get(DeckId.MAIN)
        same_subject = stored_subject is not None and stored_subject == document.subject
        # First decision for a subject counts as a new subject.
        is_new_subject = stored_subject != document.subject
        new_mode = self._decide_main_mode(document, same_subject=same_subject)
        old_mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
        if new_mode is not old_mode:
            active = self._apply_main_transition(
                document,
                preferred_card,
                old_mode=old_mode,
                new_mode=new_mode,
                is_new_subject=is_new_subject,
                previous_document=previous_document,
            )
        else:
            try:
                if new_mode is RenderMode.PAGED:
                    active = self._show_main_paged(document, preferred_card, new_mode)
                else:
                    active = self.main_view.show_document(
                        document, preferred_card=preferred_card, mode=new_mode
                    )
            except TypeError:
                active = self.main_view.show_document(
                    document, preferred_card=preferred_card
                )
            except Exception:
                active = None
            if new_mode is RenderMode.SPREAD:
                if is_new_subject:
                    # Sticky-Reply landing replaces scroll_to_card when the
                    # preferred card carries blocks; <2 blocks keeps today.
                    landed = False
                    if (
                        preferred_card is not None
                        and document.card(preferred_card) is not None
                        and preferred_card
                        != (document.cards[0].card_id if document.cards else None)
                    ):
                        try:
                            landed = bool(
                                self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                    document, preferred_card
                                )
                            )
                        except Exception:
                            landed = False
                        if landed:
                            active = self._main_active_card
                        else:
                            try:
                                self.main_view.scroll_to_card(preferred_card)
                                active = preferred_card
                            except Exception:
                                pass
                    elif (
                        preferred_card is None or document.card(preferred_card) is None
                    ):
                        # No explicit choice: sticky landing still applies when
                        # the preferred/sticky card has blocks (e.g. Reply).
                        try:
                            sticky = self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                document, preferred_card
                            )
                            if sticky:
                                active = self._main_active_card
                        except Exception:
                            pass
                else:
                    # Same-subject streaming: a follower re-lands with the
                    # clamp; a parked reader stays put. A bottom pin persists
                    # via the scheduled reapply.
                    try:
                        pinned = bool(
                            getattr(self.main_view, "is_pinned_to_bottom", False)
                        )
                    except Exception:
                        pinned = False
                    if not pinned:
                        try:
                            view = self.main_view
                            card = self._spread_block_card(  # type: ignore[attr-defined]
                                document, preferred_card
                            )
                            if card is not None:
                                try:
                                    cursor = view._block_cursors.get(card.card_id)  # type: ignore[attr-defined]
                                except Exception:
                                    cursor = None
                                if cursor is not None and bool(
                                    getattr(cursor, "following", False)
                                ):
                                    try:
                                        if bool(
                                            self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                                document,
                                                card.card_id,
                                            )
                                        ):
                                            active = self._main_active_card
                                    except Exception:
                                        pass
                        except Exception:
                            pass
            self._main_active_card = active
        self._render_mode[DeckId.MAIN] = new_mode
        self._mode_subject[DeckId.MAIN] = document.subject
        if self._deck is DeckId.MAIN:
            self.set_deck(DeckId.MAIN)
        else:
            self.refresh_chrome()
        # set_deck re-decides with same subject; guard against recursion by
        # restoring the just-decided mode when set_deck did not change it.
        self._render_mode[DeckId.MAIN] = new_mode
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._schedule_block_redecision()
        except Exception:
            pass
        return self._main_active_card

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
            if self._deck is DeckId.FILES:
                self._refresh_files_mode_for_shown()
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
