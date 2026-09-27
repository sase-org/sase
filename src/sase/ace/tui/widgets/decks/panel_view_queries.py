"""Read-only view queries for deck panels.

Content/layout/resolution third of
:mod:`sase.ace.tui.widgets.decks.panel_view`: the equivalence content
facts, the on-screen layout, policy resolution, and the cached
view-cycle predicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model import DeckId, DeckView, RenderMode
from .view_policy import ResolvedView, ViewContent, ViewStatus, resolve_view
from .view_policy import next_view as policy_next_view

if TYPE_CHECKING:
    from .main_document import MainDeckDocument

__all__ = ["DeckPanelViewQueriesMixin"]


class DeckPanelViewQueriesMixin:
    """View content, layout, resolution, and cycle queries for a panel."""

    _deck: DeckId
    _render_mode: dict[DeckId, RenderMode]
    _view_cycle_available: bool
    _files_spread_pending: bool
    _files_spread_blocked: bool
    _main_active_card: str | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    # -- Content, layout, resolution ------------------------------------

    def _view_anchor_card(self, document: MainDeckDocument) -> str | None:
        """Return the card the next paged render would show."""
        try:
            spread = bool(self.is_spread(DeckId.MAIN))
        except Exception:
            spread = False
        if spread:
            # Warm anchors: the scroll-derived card is the reading anchor.
            # Cold anchors: the sticky block card (the landing target), so a
            # fresh spread Reply already offers all three layouts.
            try:
                view = self.main_view
                width = int(view._spread_content_width())  # type: ignore[attr-defined]
                pairs = view.card_anchor_rows(width=width) if width > 0 else None
            except Exception:
                pairs = None
            if pairs:
                try:
                    derived = self._main_spread_active()
                except Exception:
                    derived = None
                if derived is not None:
                    return derived
            try:
                preferred = self._main_active_card
            except Exception:
                preferred = None
            try:
                sticky = self._spread_block_card(document, preferred)
            except Exception:
                sticky = None
            if sticky is not None:
                try:
                    return sticky.card_id
                except Exception:
                    pass
            try:
                return self._main_active_card
            except Exception:
                return None
        try:
            active = self.main_view.active_card_id
        except Exception:
            active = None
        if active is None:
            try:
                active = self._main_active_card
            except Exception:
                active = None
        return active

    def view_content(self, deck: DeckId) -> ViewContent:
        """Return the equivalence content facts for ``deck``."""
        if deck is DeckId.MAIN:
            try:
                document = self._main_document
            except Exception:
                return ViewContent(deck, 0, 0, False)
            try:
                card_count = len(document.cards)
            except Exception:
                card_count = 0
            active = self._view_anchor_card(document)
            block_count = 0
            if active is not None:
                try:
                    card = document.card(active)
                    block_count = len(card.blocks) if card is not None else 0
                except Exception:
                    block_count = 0
            return ViewContent(deck, card_count, block_count, False)
        if deck is DeckId.FILES:
            try:
                file_view = self.file_view
                slots = list(getattr(file_view, "_file_list", ()))
                card_count = len(slots)
            except Exception:
                try:
                    card_count = int(self._file_count)
                except Exception:
                    card_count = 0
            try:
                blocked = bool(self._files_spread_blocked)
            except Exception:
                blocked = False
            return ViewContent(deck, card_count, 0, blocked)
        return ViewContent(deck, 0, 0, False)

    def effective_layout(self, deck: DeckId) -> DeckView:
        """Return the on-screen layout for ``deck``."""
        if deck is DeckId.MAIN:
            try:
                mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
            except Exception:
                mode = RenderMode.PAGED
            if mode is RenderMode.SPREAD:
                return DeckView.SPREAD
            try:
                block_mode = self.main_view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.PAGED:
                return DeckView.PAGE_BLOCKS
            return DeckView.PAGE_CARDS
        if deck is DeckId.FILES:
            try:
                spread = bool(self.is_spread(DeckId.FILES))
            except Exception:
                spread = False
            return DeckView.SPREAD if spread else DeckView.PAGE_CARDS
        return DeckView.PAGE_CARDS

    def next_view(self) -> DeckView | None:
        """Return the next fixed view widening from the shown layout."""
        try:
            deck = self._deck
            if deck not in (DeckId.MAIN, DeckId.FILES):
                return None
            return policy_next_view(
                self.effective_layout(deck), self.view_content(deck)
            )
        except Exception:
            return None

    def resolved_view(self) -> ResolvedView:
        """Return the badge view for the shown deck."""
        try:
            deck = self._deck
        except Exception:
            deck = DeckId.MAIN
        try:
            policy = self.view_policy(deck)
        except Exception:
            policy = DeckView.AUTO
        try:
            effective = self.effective_layout(deck)
        except Exception:
            effective = DeckView.PAGE_CARDS
        try:
            content = self.view_content(deck)
        except Exception:
            content = ViewContent(deck, 0, 0, False)
        pending = False
        blocked = False
        if deck is DeckId.FILES:
            try:
                pending = bool(self._files_spread_pending)
            except Exception:
                pending = False
            try:
                blocked = bool(self._files_spread_blocked)
            except Exception:
                blocked = False
        try:
            return resolve_view(
                deck, policy, effective, content, pending=pending, blocked=blocked
            )
        except Exception:
            return ResolvedView(
                deck=deck,
                policy=policy,
                shown=effective,
                status=ViewStatus.OK,
            )

    # -- Cycle availability ---------------------------------------------

    @property
    def deck_view_cycle_available(self) -> bool:
        """Return the cached cycle predicate (O(1), for key gating)."""
        try:
            return bool(self._view_cycle_available)
        except Exception:
            return False

    def _compute_view_cycle_available(self) -> bool:
        """Recompute whether the focused cycle action is available."""
        try:
            deck = self._deck
        except Exception:
            return False
        if deck not in (DeckId.MAIN, DeckId.FILES):
            return False
        try:
            if bool(self._deck_is_empty(deck)):
                return False
        except Exception:
            return False
        if deck is DeckId.MAIN:
            try:
                document = self._main_document
            except Exception:
                return False
            try:
                if bool(document.partial) or not document.cards:
                    return False
            except Exception:
                return False
        try:
            return self.next_view() is not None
        except Exception:
            return False

    def _sync_view_cycle_available(self) -> None:
        """Refresh the cached predicate; poke the footer when it flips."""
        try:
            previous = bool(self._view_cycle_available)
        except Exception:
            previous = False
        try:
            current = bool(self._compute_view_cycle_available())
        except Exception:
            current = False
        try:
            self._view_cycle_available = current
        except Exception:
            pass
        if current == previous:
            return
        try:
            app = self.app
        except Exception:
            return
        refresh = getattr(app, "_refresh_agent_footer_bindings_only", None)
        if not callable(refresh):
            return
        try:
            refresh()
        except Exception:
            pass
