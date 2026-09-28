"""Card-document deck host accessors for ``DeckPanel``.

A card-document deck renders its cards through a
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView` with
spread/paged modes, scroll anchors and card blocks. Main, FINAL, and
Tools (its ``⚒ Runs`` card) are the card-document decks. Membership is
explicit (never "not Files") per the shared deck-view rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model import DeckId

if TYPE_CHECKING:
    from .document_view import CardDocumentView
    from .main_document import CardDocument


#: Card-document decks in cycle order.
CARD_DOCUMENT_DECKS: tuple[DeckId, ...] = (DeckId.MAIN, DeckId.FINAL, DeckId.TOOLS)


def is_card_document_deck(deck: DeckId) -> bool:
    """Return whether ``deck`` is a card-document deck."""
    return deck in CARD_DOCUMENT_DECKS


def resolve_document_deck(deck: DeckId) -> DeckId:
    """Return the card-document deck backing ``deck`` (exhaustive).

    Every :class:`DeckId` has an explicit arm: Main, FINAL, and Tools
    resolve to themselves, while Files (which pages file lists, not
    card documents) shares Main's host, as the legacy wrappers did.
    There is no ``else`` fall-through.
    """
    match deck:
        case DeckId.MAIN:
            return DeckId.MAIN
        case DeckId.FINAL:
            return DeckId.FINAL
        case DeckId.TOOLS:
            return DeckId.TOOLS
        case DeckId.FILES:
            return DeckId.MAIN


def spread_block_card(document: Any, preferred: str | None = None) -> Any | None:
    """Return the deck-spread card with blocks (preferred wins)."""
    try:
        if preferred is not None:
            card = document.card(preferred)
            if card is not None and bool(card.has_block_navigation):
                return card
    except Exception:
        pass
    try:
        for card in document.cards:
            if bool(getattr(card, "has_block_navigation", False)):
                return card
    except Exception:
        pass
    return None


class DeckPanelCardDocumentsMixin:
    """Host accessors routing a deck to its card-document view and document."""

    _panel_index: int
    _deck: DeckId
    _main_active_card: str | None
    _document_active_cards: dict[DeckId, str | None]

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _init_document_host_state(self) -> None:
        self._document_active_cards = {}

    def document_view(self, deck: DeckId) -> CardDocumentView:
        """Return the card-document view for ``deck`` (raises ``KeyError``).

        The Tools arm returns the Runs view only while the Runs card
        is active; while ``llm-calls`` is active there is no
        card-document view, so it raises like an unknown deck.
        """
        match deck:
            case DeckId.MAIN:
                return self.main_view  # type: ignore[attr-defined]
            case DeckId.FINAL:
                return self.final_view  # type: ignore[attr-defined]
            case DeckId.TOOLS:
                try:
                    active = self.active_tools_card()  # type: ignore[attr-defined]
                except Exception:
                    active = None
                if active == "runs":
                    return self.tool_runs_view  # type: ignore[attr-defined]
                raise KeyError(f"no card-document view for deck: {deck!r}")
            case DeckId.FILES:
                raise KeyError(f"no card-document view for deck: {deck!r}")

    def document_for(self, deck: DeckId) -> CardDocument:
        """Return the stored card document for ``deck`` (raises ``KeyError``).

        The Tools arm returns the Runs document only while the Runs
        card is active, mirroring :meth:`document_view`.
        """
        match deck:
            case DeckId.MAIN:
                return self._main_document  # type: ignore[attr-defined]
            case DeckId.FINAL:
                return self._final_document  # type: ignore[attr-defined]
            case DeckId.TOOLS:
                try:
                    active = self.active_tools_card()  # type: ignore[attr-defined]
                except Exception:
                    active = None
                if active == "runs":
                    return self._tool_runs_document  # type: ignore[attr-defined]
                raise KeyError(f"no card document for deck: {deck!r}")
            case DeckId.FILES:
                raise KeyError(f"no card document for deck: {deck!r}")

    def card_document_host(
        self, deck: DeckId
    ) -> tuple[CardDocumentView, CardDocument, DeckId] | None:
        """Return ``(view, document, deck)`` for card-document decks, else None."""
        if not is_card_document_deck(deck):
            return None
        try:
            return (self.document_view(deck), self.document_for(deck), deck)
        except Exception:
            return None

    def active_document_card(self, deck: DeckId) -> str | None:
        """Return the active card id for ``deck`` without reaching into privates."""
        if deck is DeckId.MAIN:
            try:
                return self.main_view.active_card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                return self._main_active_card
            except Exception:
                return None
        try:
            host = self.card_document_host(deck)
        except Exception:
            host = None
        if host is not None:
            try:
                return host[0].active_card_id
            except Exception:
                pass
        try:
            return self._document_active_cards.get(deck)
        except Exception:
            return None

    def _stored_document_active(self, deck: DeckId) -> str | None:
        """Return the stored (non-view) active card for ``deck``."""
        if deck is DeckId.MAIN:
            return self._main_active_card
        try:
            return self._document_active_cards.get(deck)
        except Exception:
            return None

    def _store_document_active(self, deck: DeckId, card_id: str | None) -> None:
        """Store the active card for ``deck``."""
        if deck is DeckId.MAIN:
            self._main_active_card = card_id
            return
        try:
            self._document_active_cards[deck] = card_id
        except Exception:
            pass

    def _watch_document_scroll(self, deck: DeckId) -> None:
        """Watch ``deck``'s scroll container for scroll-derived card updates."""
        from textual.containers import VerticalScroll

        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                VerticalScroll,
            )
            if deck is DeckId.MAIN:
                self.watch(scroll, "scroll_y", self._on_main_scroll_y, init=False)  # type: ignore[attr-defined]
            else:
                handler = lambda _o, _n, _d=deck: self._on_document_scroll_y(_d, _o, _n)  # noqa: E731
                self.watch(scroll, "scroll_y", handler, init=False)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_document_scroll_y(self, deck: DeckId, _old: int, _new: int) -> None:
        """Handle scroll updates for any card-document deck."""
        if self._deck is not deck:
            return
        if deck is DeckId.MAIN:
            try:
                self._on_main_scroll_y(_old, _new)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        spread = False
        try:
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
        except Exception:
            spread = False
        if spread:
            try:
                derived = self.spread_active_for(deck)  # type: ignore[attr-defined]
            except Exception:
                derived = None
            if derived is not None and derived != self._stored_document_active(deck):
                self._store_document_active(deck, derived)
                try:
                    self.refresh_chrome()  # type: ignore[attr-defined]
                except Exception:
                    pass
        try:
            self._sync_document_spread_block_cursor(deck)  # type: ignore[attr-defined]
        except Exception:
            pass


__all__ = [
    "CARD_DOCUMENT_DECKS",
    "DeckPanelCardDocumentsMixin",
    "is_card_document_deck",
    "resolve_document_deck",
    "spread_block_card",
]
