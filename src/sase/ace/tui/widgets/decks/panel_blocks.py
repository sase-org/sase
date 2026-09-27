"""Block-mode decision and paged block navigation for ``DeckPanel``.

Main-only wrappers over
:class:`~sase.ace.tui.widgets.decks.document_blocks.DeckPanelDocumentBlocksMixin`,
which holds the deck-parameterized implementation. ``card_blocks_navigable``
is a cached O(1) predicate for key gating.
"""

from __future__ import annotations

from typing import Any

from .block_rail import BlockRail, BlockRailEntry
from .card_documents import spread_block_card
from .document_blocks import DeckPanelDocumentBlocksMixin
from .model import DeckId, RenderMode


class DeckPanelBlocksMixin(DeckPanelDocumentBlocksMixin):
    """Per-panel block mode, navigation and availability for Main decks."""

    _panel_index: int
    _deck: DeckId
    _block_mode: RenderMode
    _block_mode_key: tuple[object, ...] | None
    _block_mode_measured: bool
    _block_navigable: bool
    _main_active_card: str | None

    def _init_block_panel_state(self) -> None:
        self._block_mode = RenderMode.PAGED
        self._block_mode_key = None
        self._block_mode_measured = False
        self._block_navigable = False

    def _block_settings_max_screens(self) -> float:
        return self._document_block_settings_max_screens()

    def _decide_block_mode(self, document: Any, card: Any) -> RenderMode:
        """Decide the block mode for ``card`` shown alone (§3.3)."""
        return self.decide_document_block_mode(DeckId.MAIN, document, card)

    def _schedule_block_redecision(self) -> None:
        """Retry one unmeasured block decision after layout settles."""
        self.schedule_document_block_redecision(DeckId.MAIN)

    def _block_mode_for_card(
        self, document: Any, card_id: str | None
    ) -> RenderMode | None:
        """Return the decided block mode, or None for the legacy render."""
        return self.document_block_mode_for_card(DeckId.MAIN, document, card_id)

    def _show_main_paged(
        self, document: Any, preferred_card: str | None, mode: RenderMode
    ) -> str | None:
        """Show a paged Main document with block projection when navigable."""
        return self.show_document_paged(DeckId.MAIN, document, preferred_card, mode)

    def _spread_block_card(
        self, document: Any, preferred: str | None = None
    ) -> Any | None:
        """Return the deck-spread card with blocks (preferred wins)."""
        return spread_block_card(document, preferred)

    def _land_deck_spread_on_blocks(self, document: Any, preferred: str | None) -> bool:
        """Sticky-Reply chat-log landing for a deck-spread document."""
        return self.land_document_spread_on_blocks(DeckId.MAIN, document, preferred)

    def _cycle_spread_block(self, direction: int) -> bool:
        """Anchor-motion step for spread decks and block-spread cards."""
        return self.cycle_document_spread_block(DeckId.MAIN, direction)

    def _select_spread_block(self, block_id: str | None) -> bool:
        """Direct selection for spread decks and block-spread cards."""
        return self.select_document_spread_block(DeckId.MAIN, block_id)

    def cycle_block(self, direction: int) -> bool:
        """Step the active card one block; False when a no-op."""
        if self._deck is DeckId.FINAL:
            return bool(self.cycle_document_block(DeckId.FINAL, direction))
        return self.cycle_document_block(DeckId.MAIN, direction)

    def select_block(self, block_id: str | None) -> bool:
        """Select ``block_id`` on the active card; False when a no-op."""
        if self._deck is DeckId.FINAL:
            return bool(self.select_document_block(DeckId.FINAL, block_id))
        return self.select_document_block(DeckId.MAIN, block_id)

    @property
    def card_blocks_navigable(self) -> bool:
        """Return the cached card-block navigation predicate (O(1)).

        FINAL has no cached predicate; its small documents compute live
        from the current deck instead.
        """
        if self._deck is DeckId.FINAL:
            try:
                return bool(self.compute_document_block_navigable(DeckId.FINAL))
            except Exception:
                return False
        return self.document_blocks_navigable(DeckId.MAIN)

    def active_block_id(self, card_id: str) -> str | None:
        """Return the view's active block id for ``card_id``."""
        if self._deck is DeckId.FINAL:
            return self.active_document_block_id(DeckId.FINAL, card_id)
        return self.active_document_block_id(DeckId.MAIN, card_id)

    def arrived_block_ids(self, card_id: str) -> tuple[str, ...]:
        """Return the view's unseen block ids for ``card_id``."""
        if self._deck is DeckId.FINAL:
            return self.arrived_document_block_ids(DeckId.FINAL, card_id)
        return self.arrived_document_block_ids(DeckId.MAIN, card_id)

    def block_mode_for_active_card(self) -> RenderMode | None:
        """Return the view's decided block mode for the active card."""
        if self._deck is DeckId.FINAL:
            return self.document_block_mode_for_active_card(DeckId.FINAL)
        return self.document_block_mode_for_active_card(DeckId.MAIN)

    def _needs_block_refresh(self) -> bool:
        """Return whether a stable paged deck should re-decide block mode."""
        if self._deck is DeckId.FINAL:
            return self.needs_document_block_refresh(DeckId.FINAL)
        return self.needs_document_block_refresh(DeckId.MAIN)

    def _compute_block_navigable(self) -> bool:
        """Recompute whether card-block navigation is available."""
        if self._deck is DeckId.FINAL:
            return self.compute_document_block_navigable(DeckId.FINAL)
        return self.compute_document_block_navigable(DeckId.MAIN)

    def _block_rail_widget(self) -> BlockRail | None:
        """Return the pre-composed rail widget, if it is mounted."""
        try:
            return self.query_one(BlockRail)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _block_key_hint(self) -> tuple[str, str]:
        """Return the live ``(prev, next)`` block key display names.

        Falls back to the ``(`` / ``)`` defaults when no keymap is available.
        """
        return self.document_block_key_hint()

    def _block_rail_card(self) -> Any | None:
        """Return the rail's card, or None when the rail must be hidden.

        The rail shows only when the shown deck is a paged card-document
        deck, the active card has two or more blocks, the document is a
        full paint of the current subject, and neither the search overlay
        nor the empty state is shown.
        """
        from .card_documents import is_card_document_deck

        deck = self._deck if is_card_document_deck(self._deck) else DeckId.MAIN
        return self.document_block_rail_card(deck)

    def _block_rail_cue(
        self, entries: list[BlockRailEntry], active_id: str | None
    ) -> str | None:
        """Return the rail's block-mode cue from the host's actual mode.

        Deck-aware wrapper over
        :meth:`~sase.ace.tui.widgets.decks.document_rail.DeckPanelDocumentRailMixin.document_block_rail_cue`.
        """
        from .card_documents import is_card_document_deck

        deck = self._deck if is_card_document_deck(self._deck) else DeckId.MAIN
        return self.document_block_rail_cue(deck, entries, active_id)

    def _sync_block_rail(self) -> None:
        """Show, refresh or hide the one-row block rail (never raises)."""
        from .card_documents import is_card_document_deck

        deck = self._deck if is_card_document_deck(self._deck) else DeckId.MAIN
        self.sync_document_block_rail(deck)

    def _sync_block_navigable(self) -> None:
        """Refresh the cached predicate; poke the footer when it flips."""
        from .card_documents import is_card_document_deck

        deck = self._deck if is_card_document_deck(self._deck) else DeckId.MAIN
        self.sync_document_block_navigable(deck)


__all__ = ["DeckPanelBlocksMixin"]
