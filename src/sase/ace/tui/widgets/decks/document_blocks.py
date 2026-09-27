"""Deck-parameterized card-block host for ``DeckPanel``.

When a card-document deck is paged on a card with two or more blocks, the
panel decides a block mode (block-spread versus block-paged) with the
deck's hysteresis band and drives one-block-per-page projection through
its card-document view. Every helper here takes the deck explicitly and
reaches its ``(view, document, deck)`` triple through the
:meth:`card_document_host` accessor; Main-only wrappers live in
``panel_blocks.py``.
"""

from __future__ import annotations

from typing import Any

from ...agent_decks_settings import agent_decks_settings_for
from .block_model import decide_block_mode
from .card_documents import spread_block_card
from .document_rail import DeckPanelDocumentRailMixin
from .model import DeckId, DeckView, RenderMode, resolve_active_card
from .render_mode import measure_card_rows, spread_budget_rows
from .view_policy import forced_block_mode


class DeckPanelDocumentBlocksMixin(DeckPanelDocumentRailMixin):
    """Per-panel block mode, navigation and availability for document decks."""

    _panel_index: int
    _deck: DeckId
    _block_mode: RenderMode
    _block_mode_key: tuple[object, ...] | None
    _block_mode_measured: bool
    _block_navigable: bool

    def _document_block_settings_max_screens(self) -> float:
        try:
            return float(agent_decks_settings_for(self).block_spread_max_screens)
        except Exception:
            return 1.5

    def decide_document_block_mode(
        self,
        deck: DeckId,
        document: Any,
        card: Any,
        policy: DeckView | None = None,
    ) -> RenderMode:
        """Decide the block mode for ``card`` shown alone (§3.3)."""
        if policy is None:
            try:
                policy = self.view_policy(deck)  # type: ignore[attr-defined]
            except Exception:
                policy = DeckView.AUTO
        block_count = len(card.blocks)
        key = (deck, document.subject, card.card_id)
        previous = self._block_mode if self._block_mode_key == key else None
        same_card = previous is not None
        try:
            forced = forced_block_mode(policy, block_count)
        except Exception:
            forced = None
        max_screens = self._document_block_settings_max_screens()
        rows, width = self._spread_viewport(deck)  # type: ignore[attr-defined]
        total: int | None = None
        if forced is None and rows > 0 and width > 0:
            pair = self._spread_console()  # type: ignore[attr-defined]
            if pair is not None:
                console, options = pair
                try:
                    total = measure_card_rows(
                        [card],
                        deck=deck,
                        width=width,
                        console=console,
                        options=options,
                        budget=spread_budget_rows(max_screens, rows),
                        cache_key_prefix=document.digest,
                    )
                except Exception:
                    total = None
        if forced is not None:
            mode = forced
        else:
            try:
                mode = decide_block_mode(
                    block_count=block_count,
                    card_rows=total,
                    viewport_rows=rows,
                    block_spread_max_screens=max_screens,
                    previous=previous,
                    same_card=same_card,
                )
            except Exception:
                mode = RenderMode.PAGED
        self._block_mode = mode
        self._block_mode_key = key
        self._block_mode_measured = bool(rows > 0 and width > 0 and total is not None)
        return mode

    def schedule_document_block_redecision(self, deck: DeckId) -> None:
        """Retry one unmeasured block decision after layout settles."""
        try:
            if bool(self._block_mode_measured):
                return
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return
            _view, document, _deck = host
            if document.partial:
                return
            active = self._stored_document_active(deck)  # type: ignore[attr-defined]
            if self._block_mode_key != (deck, document.subject, active):
                return
            self.call_after_refresh(lambda: self._refresh_document_mode_for_shown(deck))  # type: ignore[attr-defined]
        except Exception:
            pass

    def document_block_mode_for_card(
        self, deck: DeckId, document: Any, card_id: str | None
    ) -> RenderMode | None:
        """Return the decided block mode, or None for the legacy render."""
        try:
            if document.partial:
                return None
            if card_id is None:
                return None
            card = document.card(card_id)
            if card is None or not card.has_block_navigation:
                return None
            return self.decide_document_block_mode(deck, document, card)
        except Exception:
            return None

    def show_document_paged(
        self, deck: DeckId, document: Any, preferred_card: str | None, mode: RenderMode
    ) -> str | None:
        """Show a paged document with block projection when navigable."""
        host = self.card_document_host(deck)  # type: ignore[attr-defined]
        if host is None:
            return None
        view, _document, _deck = host
        block_mode = None
        if mode is RenderMode.PAGED and not document.partial:
            try:
                active = resolve_active_card(
                    document.card_ids, preferred_card, partial=document.partial
                )
            except Exception:
                active = None
            if active is not None:
                block_mode = self.document_block_mode_for_card(deck, document, active)
        try:
            return view.show_document(
                document,
                preferred_card=preferred_card,
                mode=mode,
                block_mode=block_mode,
            )
        except TypeError:
            return view.show_document(
                document, preferred_card=preferred_card, mode=mode
            )

    def land_document_spread_on_blocks(
        self, deck: DeckId, document: Any, preferred: str | None
    ) -> bool:
        """Sticky-Reply chat-log landing for a deck-spread document."""
        try:
            if getattr(document, "partial", False):
                return False
            card = spread_block_card(document, preferred)
            if card is None:
                return False
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, _document, _deck = host
            landed = bool(view.land_block_spread(card))  # type: ignore[attr-defined]
            if not landed:
                return False
            self._store_document_active(deck, card.card_id)  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.sync_document_block_navigable(deck)
            self.sync_document_block_rail(deck)
            return True
        except Exception:
            return False

    def cycle_document_spread_block(self, deck: DeckId, direction: int) -> bool:
        """Anchor-motion step for spread decks and block-spread cards."""
        try:
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, document, _deck = host
            if document.partial:
                return False
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
            if spread:
                try:
                    preferred = self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    preferred = None
                card = spread_block_card(document, preferred)
                if card is None:
                    return False
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = self._stored_document_active(deck)  # type: ignore[attr-defined]
                card = document.card(active) if active is not None else None
                if card is None or not card.has_block_navigation:
                    return False
                try:
                    block_mode = view.block_mode_for_active_card()
                except Exception:
                    block_mode = None
                if block_mode is not RenderMode.SPREAD:
                    return False
            try:
                ids = tuple(card.block_ids)
            except Exception:
                return False
            if len(ids) < 2:
                return False
            # The current block comes from scroll in spread modes. When
            # the viewport is above the first block header the derivation
            # is None and unknown-anchor stepping applies (] -> oldest,
            # [ -> newest); only fall back to the explicit cursor when
            # anchors are not published yet.
            current: str | None = None
            anchors_ready = False
            try:
                current = view.derive_spread_cursor(card)  # type: ignore[attr-defined]
                try:
                    width = int(view._spread_content_width())  # type: ignore[attr-defined]
                    pairs = (
                        view.block_anchor_rows(width=width)  # type: ignore[attr-defined]
                        if width > 0
                        else None
                    )
                    anchors_ready = bool(pairs)
                except Exception:
                    anchors_ready = current is not None
            except Exception:
                current = None
                anchors_ready = False
            if current is None and not anchors_ready:
                try:
                    current = view.active_block_id(card.card_id)  # type: ignore[attr-defined]
                except Exception:
                    current = None
            elif current is not None and card.block(current) is None:
                try:
                    current = view.active_block_id(card.card_id)  # type: ignore[attr-defined]
                except Exception:
                    current = None
            try:
                target = view.step_block_id_from(tuple(ids), current, direction)  # type: ignore[attr-defined]
            except Exception:
                target = None
            if target is None or card.block(target) is None:
                return False
            selected = view.select_block_cursor(card, target)
            if selected is None:
                return False
            if spread:
                # Deck-spread and block-spread stay in place; top-align the
                # target header with the block-aware reserve. scroll_to_block
                # schedules a retry when anchors are cold; the cursor is
                # already stepped, so report success.
                try:
                    view.scroll_to_block(target)  # type: ignore[attr-defined]
                except Exception:
                    pass
                moved = True
            else:
                mode = self.document_block_mode_for_card(deck, document, card.card_id)
                shown = view.show_card(card.card_id, block_mode=mode)
                if shown is None:
                    return False
                try:
                    view.scroll_to_block(target)  # type: ignore[attr-defined]
                except Exception:
                    pass
                moved = True
                shown = card.card_id
            self._store_document_active(deck, card.card_id)  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.sync_document_block_navigable(deck)
            self.sync_document_block_rail(deck)
            return bool(moved)
        except Exception:
            return False

    def select_document_spread_block(self, deck: DeckId, block_id: str | None) -> bool:
        """Direct selection for spread decks and block-spread cards."""
        try:
            if block_id is None:
                return False
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, document, _deck = host
            if document.partial:
                return False
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
            if spread:
                try:
                    preferred = self._stored_document_active(deck)  # type: ignore[attr-defined]
                except Exception:
                    preferred = None
                card = spread_block_card(document, preferred)
                if card is None:
                    return False
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = self._stored_document_active(deck)  # type: ignore[attr-defined]
                card = document.card(active) if active is not None else None
                if card is None or not card.has_block_navigation:
                    return False
                if not spread:
                    try:
                        block_mode = view.block_mode_for_active_card()
                    except Exception:
                        block_mode = None
                    if block_mode is not RenderMode.SPREAD:
                        return False
            if card.block(block_id) is None:
                return False
            selected = view.select_block_cursor(card, block_id)
            if selected is None:
                return False
            if not spread:
                mode = self.document_block_mode_for_card(deck, document, card.card_id)
                shown = view.show_card(card.card_id, block_mode=mode)
                if shown is None:
                    return False
            try:
                view.scroll_to_block(block_id)  # type: ignore[attr-defined]
            except Exception:
                pass
            moved = True
            self._store_document_active(deck, card.card_id)  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.sync_document_block_navigable(deck)
            self.sync_document_block_rail(deck)
            return bool(moved)
        except Exception:
            return False

    def cycle_document_block(self, deck: DeckId, direction: int) -> bool:
        """Step the active card one block; False when a no-op."""
        try:
            if self._deck is not deck:
                return False
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, document, _deck = host
            if document.partial:
                return False
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
            if spread:
                return bool(self.cycle_document_spread_block(deck, direction))
            try:
                active = view.active_card_id
            except Exception:
                active = self._stored_document_active(deck)  # type: ignore[attr-defined]
            card = document.card(active) if active is not None else None
            if card is None or not card.has_block_navigation:
                return False
            try:
                block_mode = view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                return bool(self.cycle_document_spread_block(deck, direction))
            stepped = view.step_block_cursor(card, direction)
            if stepped is None:
                return False
            mode = self.document_block_mode_for_card(deck, document, card.card_id)
            shown = view.show_card(card.card_id, block_mode=mode)
            if shown is None:
                return False
            self._store_document_active(deck, shown)  # type: ignore[attr-defined]
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.sync_document_block_navigable(deck)
            self.sync_document_block_rail(deck)
            return True
        except Exception:
            return False

    def select_document_block(self, deck: DeckId, block_id: str | None) -> bool:
        """Select ``block_id`` on the active card; False when a no-op."""
        try:
            if self._deck is not deck:
                return False
            host = self.card_document_host(deck)  # type: ignore[attr-defined]
            if host is None:
                return False
            view, document, _deck = host
            if document.partial:
                return False
            spread = bool(self.is_spread(deck))  # type: ignore[attr-defined]
            if spread:
                return bool(self.select_document_spread_block(deck, block_id))
            try:
                active = view.active_card_id
            except Exception:
                active = self._stored_document_active(deck)  # type: ignore[attr-defined]
            card = document.card(active) if active is not None else None
            if card is None or not card.has_block_navigation:
                return False
            try:
                block_mode = view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                return bool(self.select_document_spread_block(deck, block_id))
            selected = view.select_block_cursor(card, block_id)
            if selected is None:
                return False
            mode = self.document_block_mode_for_card(deck, document, card.card_id)
            shown = view.show_card(card.card_id, block_mode=mode)
            if shown is None:
                return False
            self._store_document_active(deck, shown)  # type: ignore[attr-defined]
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.sync_document_block_navigable(deck)
            self.sync_document_block_rail(deck)
            return True
        except Exception:
            return False


__all__ = ["DeckPanelDocumentBlocksMixin"]
