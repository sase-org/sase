"""Block-mode decision and paged block navigation for ``DeckPanel``.

When the ``card_blocks`` beta flag is on and the Main deck is paged on a
card with two or more blocks, the panel decides a block mode
(block-spread versus block-paged) with the deck's hysteresis band and
drives one-block-per-page projection through its ``MainDeckView``.
``card_blocks_navigable`` is a cached O(1) predicate for key gating.
"""

from __future__ import annotations

from typing import Any

from ...agent_decks_settings import agent_decks_settings_for
from .block_model import decide_block_mode
from .flag import card_blocks_enabled
from .model import DeckId, RenderMode, resolve_active_card
from .render_mode import measure_main_rows, spread_budget_rows


class DeckPanelBlocksMixin:
    """Per-panel block mode, navigation and availability for Main decks."""

    _panel_index: int
    _deck: DeckId
    _block_mode: RenderMode
    _block_mode_key: tuple[object, str] | None
    _block_mode_measured: bool
    _block_navigable: bool
    _main_active_card: str | None

    def _init_block_panel_state(self) -> None:
        self._block_mode = RenderMode.PAGED
        self._block_mode_key = None
        self._block_mode_measured = False
        self._block_navigable = False

    def _block_settings_max_screens(self) -> float:
        try:
            return float(agent_decks_settings_for(self).block_spread_max_screens)
        except Exception:
            return 1.5

    def _decide_block_mode(self, document: Any, card: Any) -> RenderMode:
        """Decide the block mode for ``card`` shown alone (§3.3)."""
        block_count = len(card.blocks)
        key = (document.subject, card.card_id)
        previous = self._block_mode if self._block_mode_key == key else None
        same_card = previous is not None
        max_screens = self._block_settings_max_screens()
        rows, width = self._spread_viewport(DeckId.MAIN)  # type: ignore[attr-defined]
        total: int | None = None
        if rows > 0 and width > 0:
            pair = self._spread_console()  # type: ignore[attr-defined]
            if pair is not None:
                console, options = pair
                try:
                    total = measure_main_rows(
                        [card],
                        width=width,
                        console=console,
                        options=options,
                        budget=spread_budget_rows(max_screens, rows),
                        cache_key_prefix=document.digest,
                    )
                except Exception:
                    total = None
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

    def _schedule_block_redecision(self) -> None:
        """Retry one unmeasured block decision after layout settles."""
        try:
            if not card_blocks_enabled():
                return
            if bool(self._block_mode_measured):
                return
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return
            active = self._main_active_card  # type: ignore[attr-defined]
            if self._block_mode_key != (document.subject, active):
                return
            self.call_after_refresh(self._refresh_main_mode_for_shown)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _block_mode_for_card(
        self, document: Any, card_id: str | None
    ) -> RenderMode | None:
        """Return the decided block mode, or None for the legacy render."""
        try:
            if not card_blocks_enabled():
                return None
            if document.partial:
                return None
            if card_id is None:
                return None
            card = document.card(card_id)
            if card is None or not card.has_block_navigation:
                return None
            return self._decide_block_mode(document, card)
        except Exception:
            return None

    def _show_main_paged(
        self, document: Any, preferred_card: str | None, mode: RenderMode
    ) -> str | None:
        """Show a paged Main document with block projection when navigable."""
        block_mode = None
        if mode is RenderMode.PAGED and not document.partial:
            try:
                active = resolve_active_card(
                    document.card_ids, preferred_card, partial=document.partial
                )
            except Exception:
                active = None
            if active is not None:
                block_mode = self._block_mode_for_card(document, active)
        view = self.main_view  # type: ignore[attr-defined]
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

    def _spread_block_card(
        self, document: Any, preferred: str | None = None
    ) -> Any | None:
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

    def _land_deck_spread_on_blocks(self, document: Any, preferred: str | None) -> bool:
        """Sticky-Reply chat-log landing for a deck-spread document."""
        try:
            if not card_blocks_enabled():
                return False
            if getattr(document, "partial", False):
                return False
            card = self._spread_block_card(document, preferred)
            if card is None:
                return False
            view = self.main_view  # type: ignore[attr-defined]
            landed = bool(view.land_block_spread(card))  # type: ignore[attr-defined]
            if not landed:
                return False
            self._main_active_card = card.card_id  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._sync_block_navigable()
            return True
        except Exception:
            return False

    def _cycle_spread_block(self, direction: int) -> bool:
        """Anchor-motion step for spread decks and block-spread cards."""
        try:
            if not card_blocks_enabled():
                return False
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return False
            view = self.main_view  # type: ignore[attr-defined]
            spread = bool(self.is_spread(DeckId.MAIN))  # type: ignore[attr-defined]
            if spread:
                try:
                    preferred = self._main_active_card  # type: ignore[attr-defined]
                except Exception:
                    preferred = None
                card = self._spread_block_card(document, preferred)
                if card is None:
                    return False
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = self._main_active_card  # type: ignore[attr-defined]
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
                mode = self._block_mode_for_card(document, card.card_id)
                shown = view.show_card(card.card_id, block_mode=mode)
                if shown is None:
                    return False
                try:
                    view.scroll_to_block(target)  # type: ignore[attr-defined]
                except Exception:
                    pass
                moved = True
                shown = card.card_id
            self._main_active_card = card.card_id  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._sync_block_navigable()
            return bool(moved)
        except Exception:
            return False

    def _select_spread_block(self, block_id: str | None) -> bool:
        """Direct selection for spread decks and block-spread cards."""
        try:
            if not card_blocks_enabled():
                return False
            if block_id is None:
                return False
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return False
            view = self.main_view  # type: ignore[attr-defined]
            spread = bool(self.is_spread(DeckId.MAIN))  # type: ignore[attr-defined]
            if spread:
                try:
                    preferred = self._main_active_card  # type: ignore[attr-defined]
                except Exception:
                    preferred = None
                card = self._spread_block_card(document, preferred)
                if card is None:
                    return False
            else:
                try:
                    active = view.active_card_id
                except Exception:
                    active = self._main_active_card  # type: ignore[attr-defined]
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
                mode = self._block_mode_for_card(document, card.card_id)
                shown = view.show_card(card.card_id, block_mode=mode)
                if shown is None:
                    return False
            try:
                view.scroll_to_block(block_id)  # type: ignore[attr-defined]
            except Exception:
                pass
            moved = True
            self._main_active_card = card.card_id  # type: ignore[attr-defined]
            try:
                view._active_card = card.card_id  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._sync_block_navigable()
            return bool(moved)
        except Exception:
            return False

    def cycle_block(self, direction: int) -> bool:
        """Step the active card one block; False when a no-op."""
        try:
            if self._deck is not DeckId.MAIN:
                return False
            if not card_blocks_enabled():
                return False
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return False
            spread = bool(self.is_spread(DeckId.MAIN))  # type: ignore[attr-defined]
            view = self.main_view  # type: ignore[attr-defined]
            if spread:
                return bool(self._cycle_spread_block(direction))
            try:
                active = view.active_card_id
            except Exception:
                active = self._main_active_card  # type: ignore[attr-defined]
            card = document.card(active) if active is not None else None
            if card is None or not card.has_block_navigation:
                return False
            try:
                block_mode = view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                return bool(self._cycle_spread_block(direction))
            stepped = view.step_block_cursor(card, direction)
            if stepped is None:
                return False
            mode = self._block_mode_for_card(document, card.card_id)
            shown = view.show_card(card.card_id, block_mode=mode)
            if shown is None:
                return False
            self._main_active_card = shown  # type: ignore[attr-defined]
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._sync_block_navigable()
            return True
        except Exception:
            return False

    def select_block(self, block_id: str | None) -> bool:
        """Select ``block_id`` on the active card; False when a no-op."""
        try:
            if self._deck is not DeckId.MAIN:
                return False
            if not card_blocks_enabled():
                return False
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return False
            spread = bool(self.is_spread(DeckId.MAIN))  # type: ignore[attr-defined]
            view = self.main_view  # type: ignore[attr-defined]
            if spread:
                return bool(self._select_spread_block(block_id))
            try:
                active = view.active_card_id
            except Exception:
                active = self._main_active_card  # type: ignore[attr-defined]
            card = document.card(active) if active is not None else None
            if card is None or not card.has_block_navigation:
                return False
            try:
                block_mode = view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                return bool(self._select_spread_block(block_id))
            selected = view.select_block_cursor(card, block_id)
            if selected is None:
                return False
            mode = self._block_mode_for_card(document, card.card_id)
            shown = view.show_card(card.card_id, block_mode=mode)
            if shown is None:
                return False
            self._main_active_card = shown  # type: ignore[attr-defined]
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._sync_block_navigable()
            return True
        except Exception:
            return False

    @property
    def card_blocks_navigable(self) -> bool:
        """Return the cached card-block navigation predicate (O(1))."""
        try:
            return bool(self._block_navigable)
        except Exception:
            return False

    def active_block_id(self, card_id: str) -> str | None:
        """Return the view's active block id for ``card_id``."""
        try:
            return self.main_view.active_block_id(card_id)  # type: ignore[attr-defined]
        except Exception:
            return None

    def arrived_block_ids(self, card_id: str) -> tuple[str, ...]:
        """Return the view's unseen block ids for ``card_id``."""
        try:
            return self.main_view.arrived_block_ids(card_id)  # type: ignore[attr-defined]
        except Exception:
            return ()

    def block_mode_for_active_card(self) -> RenderMode | None:
        """Return the view's decided block mode for the active card."""
        try:
            return self.main_view.block_mode_for_active_card()  # type: ignore[attr-defined]
        except Exception:
            return None

    def _needs_block_refresh(self) -> bool:
        """Return whether a stable paged deck should re-decide block mode."""
        try:
            if not card_blocks_enabled():
                return False
            if self._deck is not DeckId.MAIN:  # type: ignore[attr-defined]
                return False
            document = self._main_document  # type: ignore[attr-defined]
            if document.partial:
                return False
            active = self._main_active_card  # type: ignore[attr-defined]
            if active is None:
                try:
                    active = self.main_view.active_card_id  # type: ignore[attr-defined]
                except Exception:
                    active = None
            if active is None:
                return False
            card = document.card(active)
            return bool(card is not None and card.has_block_navigation)
        except Exception:
            return False

    def _compute_block_navigable(self) -> bool:
        """Recompute whether card-block navigation is available."""
        if not card_blocks_enabled():
            return False
        if self._deck is not DeckId.MAIN:
            return False
        document = self._main_document  # type: ignore[attr-defined]
        if document.partial:
            return False
        if self.is_spread(DeckId.MAIN):  # type: ignore[attr-defined]
            return any(bool(card.has_block_navigation) for card in document.cards)
        try:
            view = self.main_view  # type: ignore[attr-defined]
            active = view.active_card_id
        except Exception:
            active = None
        if active is None:
            try:
                active = self._main_active_card  # type: ignore[attr-defined]
            except Exception:
                active = None
        card = document.card(active) if active is not None else None
        return bool(card is not None and card.has_block_navigation)

    def _sync_block_navigable(self) -> None:
        """Refresh the cached predicate; poke the footer when it flips."""
        try:
            previous = bool(self._block_navigable)
        except Exception:
            previous = False
        try:
            current = bool(self._compute_block_navigable())
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


__all__ = ["DeckPanelBlocksMixin"]
