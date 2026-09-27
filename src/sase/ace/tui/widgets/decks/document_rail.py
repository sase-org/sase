"""Card-block rail, navigation predicate and scroll cursor per document deck.

Rail/navigable half of the deck-parameterized card-block host: the cached
O(1) navigation predicate, the one-row block rail, and the scroll-derived
spread block cursor. Main-only wrappers live in ``panel_blocks.py``.
"""

from __future__ import annotations

from typing import Any

from .block_rail import BlockRail, BlockRailEntry
from .card_documents import is_card_document_deck, spread_block_card
from .model import DeckId, RenderMode


class DeckPanelDocumentRailMixin:
    """Block rail, navigability and scroll cursor for document decks."""

    _panel_index: int
    _deck: DeckId
    _block_navigable: bool

    def document_blocks_navigable(self, deck: DeckId) -> bool:
        """Return the cached card-block navigation predicate (O(1))."""
        if deck is DeckId.MAIN:
            try:
                return bool(self._block_navigable)
            except Exception:
                return False
        return False

    def active_document_block_id(self, deck: DeckId, card_id: str) -> str | None:
        """Return the view's active block id for ``card_id`` on ``deck``."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return None
            return host[0].active_block_id(card_id)  # type: ignore[attr-defined]
        except Exception:
            return None

    def arrived_document_block_ids(self, deck: DeckId, card_id: str) -> tuple[str, ...]:
        """Return the view's unseen block ids for ``card_id`` on ``deck``."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return ()
            return host[0].arrived_block_ids(card_id)  # type: ignore[attr-defined]
        except Exception:
            return ()

    def document_block_mode_for_active_card(self, deck: DeckId) -> RenderMode | None:
        """Return the view's decided block mode for the active card on ``deck``."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return None
            return host[0].block_mode_for_active_card()  # type: ignore[attr-defined]
        except Exception:
            return None

    def needs_document_block_refresh(self, deck: DeckId) -> bool:
        """Return whether a stable paged deck should re-decide block mode."""
        try:
            if self._deck is not deck:  # type: ignore[attr-defined]
                return False
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, document, _deck = host
            if document.partial:
                return False
            active = self._stored_document_active(deck)  # type: ignore[attr-defined]
            if active is None:
                try:
                    active = view.active_card_id
                except Exception:
                    active = None
            if active is None:
                return False
            card = document.card(active)
            return bool(card is not None and card.has_block_navigation)
        except Exception:
            return False

    def compute_document_block_navigable(self, deck: DeckId) -> bool:
        """Recompute whether card-block navigation is available on ``deck``."""
        if self._deck is not deck:
            return False
        if not is_card_document_deck(deck):
            return False
        host = self.card_document_host(deck)  # type: ignore[attr-defined]
        if host is None:
            return False
        view, document, _deck = host
        if document.partial:
            return False
        if self.is_spread(deck):  # type: ignore[attr-defined]
            return any(bool(card.has_block_navigation) for card in document.cards)
        try:
            active = view.active_card_id
        except Exception:
            active = None
        if active is None:
            try:
                active = self._stored_document_active(deck)  # type: ignore[attr-defined]
            except Exception:
                active = None
        card = document.card(active) if active is not None else None
        return bool(card is not None and card.has_block_navigation)

    def document_block_rail_card(self, deck: DeckId) -> Any | None:
        """Return the rail's card for ``deck``, or None when it must hide.

        The rail shows only when the deck is a shown card-document deck and
        paged, the active card has two or more blocks, the document is a
        full paint of the current subject, and neither the search overlay
        nor the empty state is shown.
        """
        try:
            if self._deck is not deck:  # type: ignore[attr-defined]
                return None
            if not is_card_document_deck(deck):
                return None
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return None
            view, document, _deck = host
            if getattr(document, "partial", False):
                return None
            if not getattr(document, "cards", ()):
                return None
            if self._deck_is_empty(deck):  # type: ignore[attr-defined]
                return None
            if bool(self.is_spread(deck)):  # type: ignore[attr-defined]
                return None
            try:
                search = self.search_scroll()  # type: ignore[attr-defined]
                if search is not None and search.has_class("-shown"):
                    return None
            except Exception:
                pass
            try:
                active = view.active_card_id
            except Exception:
                active = None
            if active is None:
                try:
                    active = self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    active = None
            card = document.card(active) if active is not None else None
            if card is None or not bool(card.has_block_navigation):
                return None
            try:
                if view._block_cursor_subject != document.subject:  # type: ignore[attr-defined]
                    return None
            except Exception:
                pass
            return card
        except Exception:
            return None

    def document_block_key_hint(self) -> tuple[str, str]:
        """Return the live ``(prev, next)`` block key display names.

        Falls back to the ``[`` / ``]`` defaults until the card-block key
        phase registers its keymap actions.
        """
        prev, next_key = "[", "]"
        try:
            from ...keymaps import key_display_name
        except Exception:
            return (prev, next_key)
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            app_keys = getattr(registry, "app", None) if registry is not None else None
            if app_keys is None:
                return (prev, next_key)
            raw_prev = getattr(app_keys, "prev_card_block", "")
            raw_next = getattr(app_keys, "next_card_block", "")
            if raw_prev:
                prev = key_display_name(str(raw_prev)) or prev
            if raw_next:
                next_key = key_display_name(str(raw_next)) or next_key
        except Exception:
            pass
        return (prev, next_key)

    def sync_document_block_rail(self, deck: DeckId) -> None:
        """Show, refresh or hide the one-row block rail (never raises)."""
        try:
            rail = self._block_rail_widget()  # type: ignore[attr-defined]
            if rail is None:
                return
            card = self.document_block_rail_card(deck)
            if card is None:
                try:
                    rail.remove_class("-shown")
                except Exception:
                    pass
                rail.clear()
                return
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                try:
                    rail.remove_class("-shown")
                except Exception:
                    pass
                rail.clear()
                return
            view, _document, _deck = host
            try:
                active = view.active_block_id(card.card_id)
            except Exception:
                active = None
            if active is None:
                try:
                    active = card.newest_block_id
                except Exception:
                    active = None
            try:
                arrived = tuple(view.arrived_block_ids(card.card_id))
            except Exception:
                arrived = ()
            entries: list[BlockRailEntry] = []
            try:
                for block in card.blocks:
                    meta = getattr(block, "meta", None)
                    if meta is None:
                        continue
                    entries.append(BlockRailEntry(str(block.block_id), meta))
            except Exception:
                pass
            if not entries:
                try:
                    rail.remove_class("-shown")
                except Exception:
                    pass
                rail.clear()
                return
            try:
                accent = self._resolve_accent(deck)  # type: ignore[attr-defined]
            except Exception:
                accent = ""
            try:
                focused = bool(self._focused)  # type: ignore[attr-defined]
            except Exception:
                focused = True
            try:
                width = max(1, int(self._chrome_width()) - 2)  # type: ignore[attr-defined]
            except Exception:
                width = 80
            rail.set_rail(
                entries,
                active_id=active,
                arrived_ids=arrived,
                accent=accent,
                focused=focused,
                key_hint=self.document_block_key_hint(),
                width=width,
            )
            try:
                rail.add_class("-shown")
            except Exception:
                pass
        except Exception:
            pass

    def sync_document_block_navigable(self, deck: DeckId) -> None:
        """Refresh the cached predicate; poke the footer when it flips."""
        if deck is DeckId.MAIN:
            try:
                previous = bool(self._block_navigable)
            except Exception:
                previous = False
            try:
                current = bool(self.compute_document_block_navigable(deck))
            except Exception:
                current = False
            try:
                self._block_navigable = current
            except Exception:
                pass
            if current == previous:
                return
            try:
                app = self.app  # type: ignore[attr-defined]
            except Exception:
                return
            refresh = getattr(app, "_refresh_agent_footer_bindings_only", None)
            if not callable(refresh):
                return
            try:
                refresh()
            except Exception:
                pass
            return
        try:
            bool(self.compute_document_block_navigable(deck))
        except Exception:
            pass

    def sync_document_spread_block_cursor(self, deck: DeckId) -> None:
        """Recompute ``deck``'s spread block cursor from the scroll position."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return
            view, document, _deck = host
            if getattr(document, "partial", False):
                return
        except Exception:
            return
        try:
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
        except Exception:
            spread = False
        card = None
        try:
            if spread:
                try:
                    preferred = self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    preferred = None
                card = spread_block_card(document, preferred)
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = None
                if active is None:
                    try:
                        active = self._stored_document_active(deck)  # type: ignore[attr-defined]
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
            self.refresh_chrome()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.sync_document_block_navigable(deck)
        except Exception:
            pass
        try:
            self.sync_document_block_rail(deck)
        except Exception:
            pass


__all__ = ["DeckPanelDocumentRailMixin"]
