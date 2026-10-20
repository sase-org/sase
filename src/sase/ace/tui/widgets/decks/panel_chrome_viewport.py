"""Viewport scope keys, spread cues, and paged continuation for chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model import DeckId, RenderMode

if TYPE_CHECKING:
    from .titles import CardTab


class DeckPanelChromeViewportMixin:
    """Viewport-precise chrome helpers for ``DeckPanelChromeMixin``."""

    _panel_index: int
    _deck: DeckId
    _focused: bool

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _scroll_geometry(self, deck: DeckId) -> tuple[int, int, int] | None:
        """Return ``(scroll_y, viewport_height, max_scroll_y)`` for ``deck``."""
        try:
            from textual.containers import VerticalScroll
        except Exception:
            return None
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                VerticalScroll,
            )
        except Exception:
            return None
        try:
            scroll_y = int(scroll.scroll_y)
        except Exception:
            scroll_y = 0
        try:
            max_scroll_y = int(scroll.max_scroll_y)
        except Exception:
            return None
        try:
            viewport_height = int(scroll.scrollable_content_region.height)
        except Exception:
            viewport_height = 0
        if viewport_height <= 0:
            try:
                viewport_height = int(scroll.size.height)
            except Exception:
                viewport_height = 0
        return (scroll_y, max(0, viewport_height), max(0, max_scroll_y))

    def _paged_at_bottom(self, deck: DeckId) -> bool:
        """Return whether the paged ``deck`` scroller is at its bottom."""
        geometry = self._scroll_geometry(deck)
        if geometry is None:
            return False
        scroll_y, _viewport, max_scroll_y = geometry
        return int(scroll_y) >= int(max_scroll_y)

    def _continuation_key_displays(self) -> tuple[str, str, str]:
        """Return ``(card_key, block_prev, block_next)`` displays, "" when unbound."""
        try:
            from ...keymaps import key_display_name
            from ...keymaps.key_validation import is_unbound_key
        except Exception:
            return ("", "", "")
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            app_keys = getattr(registry, "app", None) if registry is not None else None
            if app_keys is None:
                return ("", "", "")
            raw_card = str(getattr(app_keys, "next_deck_card", "") or "")
            raw_prev = str(getattr(app_keys, "prev_card_block", "") or "")
            raw_next = str(getattr(app_keys, "next_card_block", "") or "")
        except Exception:
            return ("", "", "")
        try:
            card_key = (
                ""
                if (not raw_card or is_unbound_key(raw_card))
                else key_display_name(raw_card)
            )
        except Exception:
            card_key = ""
        try:
            prev_key = (
                ""
                if (not raw_prev or is_unbound_key(raw_prev))
                else key_display_name(raw_prev)
            )
        except Exception:
            prev_key = ""
        try:
            next_key = (
                ""
                if (not raw_next or is_unbound_key(raw_next))
                else key_display_name(raw_next)
            )
        except Exception:
            next_key = ""
        return (card_key or "", prev_key or "", next_key or "")

    def _spread_viewport_state(
        self,
        deck: DeckId,
        tabs: tuple[CardTab, ...],
        active_index: int | None,
    ) -> tuple[
        tuple[str, ...], str | None, tuple[str, ...], tuple[str, ...], bool, bool
    ]:
        """Return viewport ids ``(ordered, here, above, below, all_in_view, ready)``."""
        from .scope_cues import resolve_viewport_spread

        ordered = tuple(tab.card_id for tab in tabs)
        if not ordered:
            return ((), None, (), (), False, False)
        if active_index is None or not 0 <= active_index < len(ordered):
            return (ordered, None, (), (), False, False)
        here_id: str | None = ordered[active_index]
        geometry = self._scroll_geometry(deck)
        if geometry is None:
            above = tuple(ordered[:active_index])
            below = tuple(ordered[active_index + 1 :])
            return (ordered, here_id, above, below, False, False)
        scroll_y, viewport_height, max_scroll_y = geometry
        anchor_rows: tuple[tuple[str, int], ...] | None = None
        width = 0
        reserve = 0
        try:
            if deck is DeckId.FILES:
                try:
                    width = int(self._spread_viewport(deck)[1])  # type: ignore[attr-defined]
                except Exception:
                    width = 0
                if width > 0:
                    try:
                        spread_view = self.files_spread_view  # type: ignore[attr-defined]
                    except Exception:
                        spread_view = None
                    if spread_view is not None:
                        try:
                            anchor_rows = spread_view.card_anchor_rows(width=width)
                        except Exception:
                            anchor_rows = None
                        try:
                            reserve = int(spread_view.section_layout_reserve)  # type: ignore[attr-defined]
                        except Exception:
                            reserve = 0
            else:
                host = None
                try:
                    host = self.card_document_host(deck)  # type: ignore[attr-defined]
                except Exception:
                    host = None
                if host is not None:
                    view = host[0]
                    try:
                        width = int(view._spread_content_width())  # type: ignore[attr-defined]
                    except Exception:
                        width = 0
                    if width <= 0:
                        try:
                            width = int(self._spread_viewport(deck)[1])  # type: ignore[attr-defined]
                        except Exception:
                            width = 0
                    if width > 0:
                        try:
                            anchor_rows = view.card_anchor_rows(width=width)
                        except Exception:
                            anchor_rows = None
                    try:
                        reserve = int(view.section_layout_reserve)  # type: ignore[attr-defined]
                    except Exception:
                        reserve = 0
        except Exception:
            anchor_rows = None
            reserve = 0
        if anchor_rows is None:
            above = tuple(ordered[:active_index])
            below = tuple(ordered[active_index + 1 :])
            return (ordered, here_id, above, below, False, False)
        try:
            above, below, all_in_view, _ready = resolve_viewport_spread(
                ordered,
                here_id,
                anchor_rows,
                scroll_y=scroll_y,
                viewport_height=viewport_height,
                max_scroll_y=max_scroll_y,
                reserve=reserve,
            )
        except Exception:
            above = tuple(ordered[:active_index])
            below = tuple(ordered[active_index + 1 :])
            return (ordered, here_id, above, below, False, False)
        return (ordered, here_id, above, below, bool(all_in_view), True)

    def _viewport_spread_cue(
        self,
        deck: DeckId,
        tabs: tuple[CardTab, ...],
        active_index: int | None,
    ) -> Any:
        """Return the viewport-precise cue, falling back to the structural cue."""
        from .scope_cues import viewport_spread_cue
        from .title_scope import structural_spread_cue

        ordered, here_id, above, below, all_in_view, ready = (
            self._spread_viewport_state(deck, tabs, active_index)
        )
        if ready and here_id is not None:
            try:
                id_to_title = {tab.card_id: tab.title for tab in tabs}
                cue = viewport_spread_cue(
                    ordered,
                    id_to_title,
                    here_id,
                    above,
                    below,
                    all_in_view=all_in_view,
                )
                if cue is not None:
                    return cue
            except Exception:
                pass
        try:
            return structural_spread_cue(tabs, active_index)
        except Exception:
            return None

    def _build_continuation(
        self,
        deck: DeckId,
        tabs: tuple[CardTab, ...],
        *,
        paged: bool,
        at_bottom: bool,
        accent: str,
        focused: bool,
    ) -> tuple[Any, Any]:
        """Return the paged ``(full, counts-only)`` continuation cue."""
        from .scope_cues import continuation_texts

        if not paged or len(tabs) <= 1:
            return (None, None)
        try:
            block_mode = self.block_mode_for_active_card()  # type: ignore[attr-defined]
        except Exception:
            block_mode = None
        block_paged = block_mode is RenderMode.PAGED
        block_count: int | None = None
        if bool(block_paged):
            try:
                content = self.view_content(deck)  # type: ignore[attr-defined]
                block_count = int(getattr(content, "active_block_count", 0) or 0)
            except Exception:
                block_count = None
            if not block_count:
                try:
                    host = self.card_document_host(deck)  # type: ignore[attr-defined]
                except Exception:
                    host = None
                if host is not None:
                    try:
                        _view, document, _deck = host
                        active_id: str | None = None
                        try:
                            active_id = _view.active_card_id
                        except Exception:
                            active_id = None
                        card = (
                            document.card(active_id) if active_id is not None else None
                        )
                        blocks = getattr(card, "blocks", ()) if card is not None else ()
                        block_count = len(tuple(blocks))
                    except Exception:
                        block_count = None
        try:
            card_key, prev_key, next_key = self._continuation_key_displays()
        except Exception:
            card_key, prev_key, next_key = ("", "", "")
        try:
            return continuation_texts(
                deck,
                tab_count=len(tabs),
                block_count=block_count,
                block_paged=bool(block_paged),
                card_key=card_key,
                block_prev_key=prev_key,
                block_next_key=next_key,
                at_bottom=bool(at_bottom),
                focused=bool(focused),
                accent=str(accent or ""),
            )
        except Exception:
            return (None, None)

    def _shown_scope_key(self) -> tuple[Any, ...]:
        """Return the cheap hashable scope key for the shown deck."""
        from .spec import coerce_known_deck

        try:
            deck = coerce_known_deck(self._deck, context="chrome.scope_key")
        except Exception:
            return ("unknown",)
        try:
            if deck is DeckId.MAIN:
                tabs = self._main_tabs()
            elif deck is DeckId.FILES:
                tabs = self._files_tabs()
            elif deck is DeckId.TOOLS:
                tabs = self._tools_tabs()
            elif deck is DeckId.FINAL:
                tabs = self._final_tabs()
            elif deck is DeckId.RECORD:
                tabs = self._record_tabs()
            else:
                return (deck.value, "unknown")
        except Exception:
            return (deck.value, "unknown")
        try:
            active_index = self._active_tab_index()
        except Exception:
            active_index = None
        try:
            tabs, active_index = self._held_title_tabs(deck, tuple(tabs), active_index)
        except Exception:
            pass
        try:
            view = self._chrome_view(deck)
        except Exception:
            view = None
        try:
            paged = self._title_is_paged(deck, tuple(tabs), view)
        except Exception:
            paged = len(tuple(tabs)) > 1
        if paged:
            try:
                at_bottom = self._paged_at_bottom(deck)
            except Exception:
                at_bottom = False
            return (deck.value, "paged", bool(at_bottom))
        ordered = tuple(tab.card_id for tab in tabs)
        if not ordered:
            return (deck.value, "empty")
        if active_index is None or not 0 <= active_index < len(ordered):
            return (deck.value, "spread", None, (), (), False)
        try:
            _ordered, here_id, above, below, all_in_view, _ready = (
                self._spread_viewport_state(deck, tuple(tabs), active_index)
            )
        except Exception:
            here_id = ordered[active_index]
            above = tuple(ordered[:active_index])
            below = tuple(ordered[active_index + 1 :])
            all_in_view = False
        return (
            deck.value,
            "spread",
            here_id,
            tuple(above),
            tuple(below),
            bool(all_in_view),
        )

    def _refresh_chrome_if_scope_changed(self) -> bool:
        """Recompute chrome only when the viewport scope key changed."""
        try:
            key = self._shown_scope_key()
        except Exception:
            return False
        try:
            previous = getattr(self, "_viewport_scope_key", None)
        except Exception:
            previous = None
        if previous is not None and tuple(previous) == tuple(key):
            return False
        try:
            self.refresh_chrome()
        except Exception:
            return False
        return True

    def _on_deck_section_layout(self, deck: DeckId) -> None:
        """Refresh chrome after layout publishes when the scope key moved."""
        try:
            if deck is not self._deck:  # type: ignore[attr-defined]
                return
        except Exception:
            return
        try:
            self._refresh_chrome_if_scope_changed()
        except Exception:
            pass


__all__ = ["DeckPanelChromeViewportMixin"]
