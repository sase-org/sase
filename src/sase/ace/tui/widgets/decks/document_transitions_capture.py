"""Capture and restore hierarchical reading anchors for card-document decks.

Capture first of :mod:`sase.ace.tui.widgets.decks.document_transitions`:
one :class:`~sase.ace.tui.widgets.decks._document_transitions.ReadingAnchor`
records ``(card_id, block_id, offset_rows, pinned)`` before a spread/paged
recomposition, and restore lands the most specific target that survives.
"""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll

from ._document_transitions import ReadingAnchor, document_view
from .block_model import derive_spread_block
from .main_view_blocks import sync_scrollbar_position
from .model import DeckId, RenderMode

__all__ = ["DeckPanelDocumentCaptureMixin"]


def _document_scroll(panel: Any, deck: DeckId) -> VerticalScroll | None:
    try:
        return panel.query_one(
            f"#agent-deck-panel-{panel._panel_index}-{deck.value}-scroll",
            VerticalScroll,
        )
    except Exception:
        return None


def _scroll_y(panel: Any, deck: DeckId) -> int:
    try:
        scroll = _document_scroll(panel, deck)
        if scroll is not None:
            return int(scroll.scroll_y)
    except Exception:
        pass
    return 0


def _is_pinned(panel: Any, deck: DeckId) -> bool:
    try:
        view = document_view(panel, deck)
        return bool(getattr(view, "is_pinned_to_bottom", False))
    except Exception:
        return False


def _blocks_enabled(panel: Any, document: Any) -> bool:
    try:
        if getattr(document, "partial", False):
            return False
    except Exception:
        return False
    return True


def _card_with_blocks(document: Any, card_id: str | None) -> Any | None:
    if card_id is None:
        return None
    try:
        card = document.card(card_id)
    except Exception:
        return None
    try:
        if card is not None and bool(card.has_block_navigation):
            return card
    except Exception:
        return None
    return None


def _block_row(panel: Any, deck: DeckId, block_id: str) -> int | None:
    try:
        view = document_view(panel, deck)
    except Exception:
        return None
    if view is None:
        return None
    try:
        width = int(view._spread_content_width())
    except Exception:
        width = 0
    if width <= 0:
        return None
    try:
        pairs = view.block_anchor_rows(width=width)
    except Exception:
        pairs = None
    if not pairs:
        return None
    for bid, row in pairs:
        if bid == block_id:
            return int(row)
    return None


def _at_real_bottom(panel: Any, deck: DeckId) -> bool:
    try:
        view = document_view(panel, deck)
        scroll = _document_scroll(panel, deck)
        if view is None or scroll is None:
            return False
        target = int(view.bottom_scroll_target(scroll))
        return _scroll_y(panel, deck) >= target
    except Exception:
        return False


def _capture_panel_anchor(
    panel: Any, deck: DeckId, document: Any, *, old_mode: RenderMode
) -> ReadingAnchor:
    """Capture the hierarchical reading position before recomposition."""
    scroll_y = _scroll_y(panel, deck)
    pinned = _is_pinned(panel, deck)
    card_id: str | None = None
    try:
        if old_mode is RenderMode.SPREAD:
            card_id = panel.spread_active_for(deck) or panel._stored_document_active(
                deck
            )
        else:
            try:
                view = document_view(panel, deck)
                card_id = view.active_card_id if view is not None else None
            except Exception:
                card_id = None
            if card_id is None:
                card_id = panel._stored_document_active(deck)
    except Exception:
        try:
            card_id = panel._stored_document_active(deck)
        except Exception:
            card_id = None
    block_id: str | None = None
    offset = 0
    if old_mode is RenderMode.SPREAD and document is not None:
        # Deck-spread: derive the scroll block when the anchor card has blocks.
        anchor_card = (
            _card_with_blocks(document, card_id)
            if _blocks_enabled(panel, document)
            else None
        )
        if anchor_card is not None:
            derived: str | None = None
            try:
                view = document_view(panel, deck)
                width = int(view._spread_content_width()) if view is not None else 0
                pairs = (
                    view.block_anchor_rows(width=width)
                    if view is not None and width > 0
                    else None
                )
                if pairs:
                    derived = derive_spread_block(
                        pairs,
                        scroll_y=float(scroll_y),
                        at_real_bottom=_at_real_bottom(panel, deck),
                    )
                if derived is None and view is not None:
                    # Fall back to the explicit cursor so a pre-scroll
                    # landing still anchors the newest block.
                    try:
                        derived = view.active_block_id(anchor_card.card_id)
                    except Exception:
                        derived = None
            except Exception:
                derived = None
            if derived is not None and anchor_card.block(derived) is not None:
                block_id = derived
                row = _block_row(panel, deck, derived)
                if row is not None:
                    offset = max(0, scroll_y - row)
                else:
                    offset = 0
                return ReadingAnchor(
                    card_id=card_id,
                    block_id=block_id,
                    offset_rows=max(0, int(offset)),
                    pinned=pinned,
                )
        # No block anchor: today's spread math.
        try:
            view = document_view(panel, deck)
            body_start = (
                view.spread_body_start(card_id or "") if view is not None else None
            )
        except Exception:
            body_start = None
        if body_start is not None:
            offset = max(0, scroll_y - int(body_start))
        else:
            # Paged-origin offsets keep the raw scroll_y; spread-origin
            # offsets without a body start collapse to the card top.
            offset = 0 if old_mode is RenderMode.SPREAD else int(scroll_y)
        return ReadingAnchor(
            card_id=card_id,
            block_id=None,
            offset_rows=max(0, int(offset)),
            pinned=pinned,
        )
    # Paged deck: prefer the explicit cursor for block-paged, derive for
    # block-spread (the scroll position is the source of truth there).
    if _blocks_enabled(panel, document):
        card = _card_with_blocks(document, card_id)
        if card is not None:
            candidate: str | None = None
            try:
                view = document_view(panel, deck)
                block_mode = (
                    view.block_mode_for_active_card() if view is not None else None
                )
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                try:
                    view = document_view(panel, deck)
                    width = int(view._spread_content_width()) if view is not None else 0
                    pairs = (
                        view.block_anchor_rows(width=width)
                        if view is not None and width > 0
                        else None
                    )
                    if pairs:
                        candidate = derive_spread_block(
                            pairs,
                            scroll_y=float(scroll_y),
                            at_real_bottom=_at_real_bottom(panel, deck),
                        )
                except Exception:
                    candidate = None
                if candidate is None or card.block(candidate) is None:
                    try:
                        view = document_view(panel, deck)
                        candidate = (
                            view.active_block_id(card.card_id)
                            if view is not None
                            else None
                        )
                    except Exception:
                        candidate = None
            else:
                try:
                    view = document_view(panel, deck)
                    candidate = (
                        view.active_block_id(card.card_id) if view is not None else None
                    )
                except Exception:
                    candidate = None
            if candidate is not None and card.block(candidate) is not None:
                block_id = candidate
                row = _block_row(panel, deck, candidate)
                if row is not None:
                    offset = max(0, scroll_y - row)
                else:
                    # Block-paged pages start at the top; the intra-page
                    # offset is the scroll position itself.
                    offset = max(0, int(scroll_y))
                return ReadingAnchor(
                    card_id=card_id,
                    block_id=block_id,
                    offset_rows=max(0, int(offset)),
                    pinned=pinned,
                )
    # Today's paged math: the PAGED->SPREAD offset is the raw scroll_y and
    # is restored against the spread body start by the caller.
    offset = max(0, int(scroll_y))
    return ReadingAnchor(
        card_id=card_id, block_id=None, offset_rows=offset, pinned=pinned
    )


def _synced_block_scroll_to(panel: Any, deck: DeckId, target: int) -> None:
    """Scroll ``deck``'s scroller and pin its scrollbar thumb.

    The scroll is immediate so ``ScrollBar.position`` tracks the scroller
    while the bar is still shown; the deferred sync covers the layout shrink
    that hides the bar before clamping ``scroll_y`` (the block-spread to
    block-paged stale-thumb race).
    """
    try:
        scroll = _document_scroll(panel, deck)
        if scroll is not None:
            scroll.scroll_to(y=target, animate=False, immediate=True)
            try:
                panel.call_after_refresh(lambda: sync_scrollbar_position(scroll))
            except Exception:
                pass
    except Exception:
        pass


def _restore_block_offset(
    panel: Any, deck: DeckId, anchor: ReadingAnchor, *, fallback_target: int = 0
) -> None:
    """Scroll to ``block row + offset`` with a bounded post-layout retry."""

    def _apply(attempt: int) -> None:
        row = (
            _block_row(panel, deck, anchor.block_id)
            if anchor.block_id is not None
            else None
        )
        if row is None:
            if attempt >= 3:
                # The block anchor never published: fall back to the
                # card top so the reader is not left at an unrelated offset.
                _synced_block_scroll_to(panel, deck, max(0, fallback_target))
                return
            try:
                panel.call_after_refresh(lambda: _apply(attempt + 1))
            except Exception:
                pass
            return
        target = max(0, int(row) + max(0, int(anchor.offset_rows)))
        _synced_block_scroll_to(panel, deck, target)

    try:
        # Same-cycle fast path: anchors already cached, no flash of the
        # oldest block.
        row = (
            _block_row(panel, deck, anchor.block_id)
            if anchor.block_id is not None
            else None
        )
        if row is not None:
            target = max(0, int(row) + max(0, int(anchor.offset_rows)))
            _synced_block_scroll_to(panel, deck, target)
            return
        panel.call_after_refresh(lambda: _apply(0))
    except Exception:
        pass


class DeckPanelDocumentCaptureMixin:
    """Capture and restore hierarchical reading anchors for one card-document deck."""

    _panel_index: int

    def _capture_document_reading_anchor(
        self, deck: DeckId, document: Any, *, old_mode: RenderMode
    ) -> ReadingAnchor:
        return _capture_panel_anchor(self, deck, document, old_mode=old_mode)

    def _restore_document_block_transition(
        self, deck: DeckId, anchor: ReadingAnchor, active: str | None
    ) -> None:
        """Restore a block-anchored position after a mode recomposition."""
        host = self.card_document_host(deck)  # type: ignore[attr-defined]
        view = host[0] if host is not None else None
        if anchor.pinned:
            try:
                if view is not None:
                    view.pin_to_bottom()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if anchor.block_id is None or anchor.card_id is None:
            return
        if host is None:
            return
        _view, document, _deck = host
        card = _card_with_blocks(document, anchor.card_id)
        if card is None or card.block(anchor.block_id) is None:
            return
        if active is not None and active != anchor.card_id:
            return
        # Offsets clamp at 0, so a bottom-landed newest block becomes the
        # newest page's top.
        _restore_block_offset(self, deck, anchor, fallback_target=0)
