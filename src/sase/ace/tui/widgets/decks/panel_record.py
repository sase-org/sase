"""RECORD deck handling for ``DeckPanel`` (epic sase-1jm.4.2, ``shell``).

Extracted into its own mixin so the panel shell stays under the
line-count gate (``panel_navigation.py`` is already at ~640 lines).
All cross-mixin collaborators are reached through ``self``; this
module imports only public names and never a ``_``-prefixed symbol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .main_document import MainDeckDocument
from .model import DeckId, cycle_card_id


class DeckPanelRecordMixin:
    """RECORD document push, load handling, and card cycling."""

    _deck: DeckId
    _record_document: MainDeckDocument

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def handle_record_deck_loaded(self, message: Any) -> None:
        """Store a freshly loaded RECORD document and refresh chrome.

        The originating view already painted; this records the
        document for tabs and the empty state without disturbing the
        active card.
        """
        try:
            document = message.document
        except Exception:
            return
        self._record_document = document
        try:
            active = message.active_card
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.RECORD, active)  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._deck is DeckId.RECORD:
            try:
                self.set_deck(DeckId.RECORD)  # type: ignore[attr-defined]
            except Exception:
                try:
                    self.refresh_chrome()  # type: ignore[attr-defined]
                except Exception:
                    pass
        else:
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            message.stop()
        except Exception:
            pass

    def show_record_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
    ) -> str | None:
        """Push ``document`` to the RECORD view; return the active card."""
        self._record_document = document
        try:
            from .model import resolve_active_card

            pending = resolve_active_card(
                document.card_ids, preferred_card, partial=document.partial
            )
            block_mode = self.document_block_mode_for_card(  # type: ignore[attr-defined]
                DeckId.RECORD, document, pending
            )
        except Exception:
            block_mode = None
        try:
            try:
                active = self.record_view.show_record_document(  # type: ignore[attr-defined]
                    document, preferred_card, block_mode=block_mode
                )
            except TypeError:
                active = self.record_view.show_record_document(  # type: ignore[attr-defined]
                    document, preferred_card
                )
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.RECORD, active)  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._deck is DeckId.RECORD:
            try:
                self.set_deck(DeckId.RECORD)  # type: ignore[attr-defined]
            except Exception:
                try:
                    self.refresh_chrome()  # type: ignore[attr-defined]
                except Exception:
                    pass
        else:
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
        return active

    def _cycle_record_card(self, direction: int) -> str | None:
        """Cycle RECORD cards (Lifecycle/Provenance/Relations/Links)."""
        if self.is_spread(DeckId.RECORD):  # type: ignore[attr-defined]
            return self._cycle_document_spread(DeckId.RECORD, direction)  # type: ignore[attr-defined]
        try:
            ids = [card.card_id for card in self._record_document.cards]
        except Exception:
            return None
        try:
            active = self.record_view.active_card_id  # type: ignore[attr-defined]
        except Exception:
            try:
                active = self._stored_document_active(DeckId.RECORD)  # type: ignore[attr-defined]
            except Exception:
                active = None
        next_id = cycle_card_id(ids, active, direction)
        if next_id is None:
            return None
        try:
            block_mode = self.document_block_mode_for_card(  # type: ignore[attr-defined]
                DeckId.RECORD, self._record_document, next_id
            )
        except Exception:
            block_mode = None
        try:
            try:
                shown = self.record_view.show_card(next_id, block_mode=block_mode)  # type: ignore[attr-defined]
            except TypeError:
                shown = self.record_view.show_card(next_id)  # type: ignore[attr-defined]
        except Exception:
            return None
        if shown is None:
            return None
        try:
            self._store_document_active(DeckId.RECORD, shown)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.refresh_chrome()  # type: ignore[attr-defined]
        return shown


__all__ = ["DeckPanelRecordMixin"]
