"""Apply and refresh card-document deck spread/paged transitions.

Apply second of :mod:`sase.ace.tui.widgets.decks.document_transitions`:
the sticky preferred-card lookup, the shown-document mode refresh, and
the spread/paged apply that restores the captured hierarchical anchor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll

from ._document_transitions import ReadingAnchor, document_view
from .model import DeckId, RenderMode

__all__ = ["DeckPanelDocumentApplyMixin"]


class DeckPanelDocumentApplyMixin:
    """Apply and refresh spread/paged transitions for one card-document deck."""

    _panel_index: int

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _preferred_document_card(self, deck: DeckId) -> str | None:
        """Return the sticky preferred card for ``deck`` (area state for Main)."""
        if deck is DeckId.MAIN:
            try:
                return self._preferred_card_from_area()  # type: ignore[attr-defined]
            except Exception:
                return None
        try:
            return self._stored_document_active(deck)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _refresh_document_mode_for_shown(self, deck: DeckId) -> None:
        host = self.card_document_host(deck)  # type: ignore[attr-defined]
        if host is None:
            return
        view, document, _deck = host
        if not document.cards or document.partial:
            return
        stored = self._mode_subject.get(deck)  # type: ignore[attr-defined]
        same = stored is not None and stored == document.subject
        new_mode = self._decide_document_mode(deck, document, same_subject=same)  # type: ignore[attr-defined]
        old_mode = self._render_mode.get(deck, RenderMode.PAGED)  # type: ignore[attr-defined]
        if new_mode is old_mode:
            # Deck mode is stable, but the block mode may be stale
            # (unmeasured first paint, resize, split or header toggles).
            # A block spread<->paged flip keeps the reader's block and
            # offset via one hierarchical anchor.
            try:
                if new_mode is RenderMode.PAGED and self.needs_document_block_refresh(  # type: ignore[attr-defined]
                    deck
                ):
                    anchor = self._capture_document_reading_anchor(
                        deck, document, old_mode=old_mode
                    )
                    active = self.show_document_paged(  # type: ignore[attr-defined]
                        deck,
                        document,
                        self._stored_document_active(deck),  # type: ignore[attr-defined]
                        new_mode,  # type: ignore[attr-defined]
                    )
                    self._store_document_active(deck, active)  # type: ignore[attr-defined]
                    try:
                        self._restore_document_block_transition(deck, anchor, active)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                self.sync_document_block_navigable(deck)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        preferred = self._preferred_document_card(deck)
        # Avoid recursion via set_deck: apply directly.
        self._render_mode[deck] = new_mode  # type: ignore[attr-defined]
        self._mode_subject[deck] = document.subject  # type: ignore[attr-defined]
        try:
            if new_mode is RenderMode.SPREAD:
                view.show_document(  # type: ignore[attr-defined]
                    document, preferred_card=preferred, mode=new_mode
                )
                if (
                    preferred is not None
                    and document.card(preferred) is not None
                    and preferred
                    != (document.cards[0].card_id if document.cards else None)
                ):
                    try:
                        view.scroll_to_card(preferred)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    # Deck-spread sticky landing for the preferred block card.
                    try:
                        landed = self.land_document_spread_on_blocks(  # type: ignore[attr-defined]
                            deck, document, preferred
                        )
                        if landed:
                            self._store_document_active(  # type: ignore[attr-defined]
                                deck,
                                view.active_card_id,  # type: ignore[attr-defined]
                            )
                            return
                    except Exception:
                        pass
                self._store_document_active(deck, view.active_card_id)  # type: ignore[attr-defined]
            else:
                spread_active = self.spread_active_for(  # type: ignore[attr-defined]
                    deck
                ) or self._stored_document_active(deck)  # type: ignore[attr-defined,operator]
                transition_anchor: ReadingAnchor | None = None
                try:
                    transition_anchor = self._capture_document_reading_anchor(
                        deck, document, old_mode=old_mode
                    )
                    if transition_anchor.block_id is not None:
                        spread_active = transition_anchor.card_id or spread_active
                except Exception:
                    transition_anchor = None
                active = self.show_document_paged(  # type: ignore[attr-defined]
                    deck, document, spread_active or preferred, new_mode
                )
                self._store_document_active(deck, active)  # type: ignore[attr-defined]
                if (
                    transition_anchor is not None
                    and transition_anchor.block_id is not None
                ):
                    try:
                        self._restore_document_block_transition(
                            deck, transition_anchor, active
                        )  # type: ignore[attr-defined]
                    except Exception:
                        pass
        except Exception:
            pass
        self._sync_files_views()  # type: ignore[attr-defined]
        self.refresh_chrome()  # type: ignore[attr-defined]
        try:
            self.sync_document_block_navigable(deck)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _apply_document_transition(
        self,
        deck: DeckId,
        document: Any,
        preferred_card: str | None,
        *,
        old_mode: RenderMode,
        new_mode: RenderMode,
        is_new_subject: bool,
        previous_document: Any,
    ) -> str | None:
        # Capture reading position before recomposing.
        scroll_y = 0
        pinned = False
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                VerticalScroll,
            )
            scroll_y = int(scroll.scroll_y)
        except Exception:
            scroll = None
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            view = host[0] if host is not None else None
            pinned = bool(getattr(view, "is_pinned_to_bottom", False))
        except Exception:
            pinned = False
            view = None
        anchor_card: str | None = None
        offset = 0
        anchor: ReadingAnchor | None = None
        try:
            anchor = self._capture_document_reading_anchor(
                deck, document, old_mode=old_mode
            )
        except Exception:
            anchor = None
        if anchor is not None and anchor.block_id is not None:
            anchor_card = anchor.card_id
            offset = anchor.offset_rows
            pinned = anchor.pinned
        elif old_mode is RenderMode.SPREAD and new_mode is RenderMode.PAGED:
            anchor_card = self.spread_active_for(deck) or self._stored_document_active(  # type: ignore[attr-defined,operator]
                deck
            )
            try:
                body_start = (
                    view.spread_body_start(anchor_card or "")
                    if view is not None
                    else None
                )  # type: ignore[attr-defined]
            except Exception:
                body_start = None
            if body_start is not None:
                offset = max(0, scroll_y - body_start)
            else:
                offset = 0
        elif old_mode is RenderMode.PAGED and new_mode is RenderMode.SPREAD:
            anchor_card = self._stored_document_active(deck)  # type: ignore[attr-defined]
            offset = scroll_y
        try:
            if new_mode is RenderMode.SPREAD:
                if view is None:
                    active = None
                else:
                    active = view.show_document(  # type: ignore[attr-defined]
                        document, preferred_card=preferred_card, mode=new_mode
                    )
            else:
                # The sticky preferred card (the user's explicit choice)
                # wins the card decision over a scroll-derived anchor, which
                # can still point at the previous card while layout settles
                # under load. The anchor still owns the scroll offset restore
                # below. Without a recorded choice the anchor rules as before.
                active = self.show_document_paged(  # type: ignore[attr-defined]
                    deck,
                    document,
                    preferred_card or anchor_card,
                    new_mode,
                )
        except Exception:
            active = None
        self._store_document_active(deck, active)  # type: ignore[attr-defined]
        if new_mode is RenderMode.SPREAD:
            if (
                preferred_card is not None
                and document.card(preferred_card) is not None
                and preferred_card
                != (document.cards[0].card_id if document.cards else None)
            ):
                try:
                    if view is not None:
                        view.scroll_to_card(preferred_card)  # type: ignore[attr-defined]
                    self._store_document_active(deck, preferred_card)  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    return self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    return None
            # Sticky-Reply landing replaces the top start when the
            # preferred card carries blocks.
            try:
                landed = self.land_document_spread_on_blocks(  # type: ignore[attr-defined]
                    deck, document, preferred_card
                )
                if landed:
                    return self._stored_document_active(deck)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                return self._stored_document_active(deck)  # type: ignore[attr-defined]
            except Exception:
                return None
        if pinned:
            try:
                if view is not None:
                    view.pin_to_bottom()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                return self._stored_document_active(deck)  # type: ignore[attr-defined]
            except Exception:
                return None
        # Anchor the reading position after layout settles.
        try:
            if anchor is not None and anchor.block_id is not None:
                self._restore_document_block_transition(deck, anchor, active)
                try:
                    return self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    return None
            if new_mode is RenderMode.PAGED:

                def _restore_paged() -> None:
                    try:
                        sc = self.query_one(  # type: ignore[attr-defined]
                            f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                            VerticalScroll,
                        )
                        sc.scroll_to(y=max(0, offset), animate=False)
                    except Exception:
                        pass

                self.call_after_refresh(_restore_paged)  # type: ignore[attr-defined]
            else:
                base = anchor_card or (active or "")

                def _spread_body(row_base: str) -> int | None:
                    try:
                        v = document_view(self, deck)
                        return (
                            v.spread_body_start(row_base)
                            if row_base and v is not None
                            else None
                        )  # type: ignore[attr-defined]
                    except Exception:
                        return None

                body = _spread_body(base)
                target_spread = (body or 0) + offset

                def _restore_spread() -> None:
                    row = _spread_body(base)
                    target = (row or 0) + offset if row is not None else target_spread
                    try:
                        sc = self.query_one(  # type: ignore[attr-defined]
                            f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                            VerticalScroll,
                        )
                        sc.scroll_to(y=target, animate=False)
                    except Exception:
                        pass

                self.call_after_refresh(_restore_spread)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            return self._stored_document_active(deck)  # type: ignore[attr-defined]
        except Exception:
            return None
