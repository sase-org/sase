"""Private implementation pieces for DeckPanel spread state."""

from __future__ import annotations


from textual.containers import VerticalScroll

from ._panel_spread_decisions import PanelSpreadDecisionMixin
from .model import DeckId, RenderMode, cycle_card_id


class PanelSpreadCardsMixin(PanelSpreadDecisionMixin):
    """Track and cycle the active card in spread views."""

    def spread_active_for(self, deck: DeckId) -> str | None:
        """Return the scroll-derived active card for any card-document ``deck``."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
        except Exception:
            host = None
        if host is None:
            return None
        view, _document, _deck = host
        try:
            if view.render_mode is not RenderMode.SPREAD:
                return self._stored_document_active(deck)  # type: ignore[attr-defined]
            return view.spread_active_card()
        except Exception:
            try:
                return self._stored_document_active(deck)  # type: ignore[attr-defined]
            except Exception:
                return None

    def _document_spread_active(self, deck: DeckId) -> str | None:
        """Return the scroll-derived active card for ``deck``."""
        return self.spread_active_for(deck)

    def _main_spread_active(self) -> str | None:
        try:
            view = self.main_view  # type: ignore[attr-defined]
            if view.render_mode is not RenderMode.SPREAD:
                return getattr(self, "_main_active_card", None)
            return view.spread_active_card()
        except Exception:
            return getattr(self, "_main_active_card", None)

    def _files_spread_active_index(self) -> int:
        try:
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            pages = list(spread_view.page_slots)
            if not pages:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            width = self._spread_viewport(DeckId.FILES)[1]
            if width <= 0:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            pairs = spread_view.card_anchor_rows(width=width)
            if not pairs:
                return 0
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            scroll_y = int(scroll.scroll_y)
            active_index = 0
            for cid, row in sorted(pairs, key=lambda item: item[1]):
                if row <= scroll_y:
                    try:
                        if cid.startswith("file-"):
                            active_index = int(cid[len("file-") :])
                    except Exception:
                        pass
                else:
                    break
            # First page anchor is implicit row 0; already covered by index 0.
            file_view = self.file_view  # type: ignore[attr-defined]
            count = len(getattr(file_view, "_file_list", pages))
            return max(0, min(active_index, max(0, count - 1)))
        except Exception:
            try:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            except Exception:
                return 0

    def _files_anchor_row(self, index: int) -> int | None:
        """Return the titled-separator row for Files page ``index``."""
        if index <= 0:
            return 0
        try:
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            width = self._spread_viewport(DeckId.FILES)[1]
            if width <= 0:
                return None
            pairs = spread_view.card_anchor_rows(width=width)
            if not pairs:
                return None
            want = f"file-{index}"
            for cid, row in pairs:
                if cid == want:
                    return row
            return None
        except Exception:
            return None

    def _files_body_start(self, index: int) -> int | None:
        """Return the body start row for Files page ``index``.

        Body start is one row below the titled separator so spread/paged
        transition math can restore a reading offset inside the page.
        """
        if index <= 0:
            return 0
        anchor = self._files_anchor_row(index)
        if anchor is None:
            return None
        return anchor + 1

    def _cycle_document_spread(self, deck: DeckId, direction: int) -> str | None:
        """Cycle spread cards on any card-document ``deck``."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
        except Exception:
            host = None
        if host is None:
            return None
        view, document, _deck = host
        ids = [card.card_id for card in document.cards]
        if not ids:
            return None
        active = self.spread_active_for(deck)
        next_id = cycle_card_id(ids, active, direction)
        if next_id is None:
            return None
        try:
            shown = view.scroll_to_card(next_id)
        except Exception:
            return None
        if shown is None:
            return None
        try:
            self._store_document_active(deck, shown)  # type: ignore[attr-defined]
        except Exception:
            return None
        try:
            self.refresh_chrome()  # type: ignore[attr-defined]
        except Exception:
            pass
        return shown

    def _cycle_main_spread(self, direction: int) -> str | None:
        return self._cycle_document_spread(DeckId.MAIN, direction)
