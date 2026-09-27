"""Per-panel deck-view policies with anchor-preserving Main transitions.

``DeckPanelViewMixin`` stores the ``DeckViewPolicies`` for a deck panel and
applies Main policies through one view-change transition that keeps the
reader's card, block, offset, pin, and following in every direction. Files
policies are stored here; the Files probe honors them in files-engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll

from .main_view_blocks import sync_scrollbar_position
from .model import DeckId, DeckView, DeckViewPolicies, RenderMode
from .view_policy import (
    ResolvedView,
    ViewContent,
    forced_block_mode,
    forced_deck_mode,
)
from .view_policy import next_view as _policy_next_view
from .view_policy import resolve_view

if TYPE_CHECKING:
    from .main_document import MainDeckDocument

__all__ = ["DeckPanelViewMixin"]


class DeckPanelViewMixin:
    """View policies, predicates, and the Main view-change transition."""

    _panel_index: int
    _deck: DeckId
    _render_mode: dict[DeckId, RenderMode]
    _mode_subject: dict[DeckId, object]
    _block_mode_key: tuple[object, str] | None
    _view_policies: DeckViewPolicies
    _view_generation: int
    _pending_view_anchor: tuple[object, Any, int] | None
    _view_cycle_available: bool
    _files_spread_pending: bool
    _files_spread_blocked: bool
    _main_active_card: str | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _init_view_state(self) -> None:
        self._view_policies = DeckViewPolicies()
        self._view_generation = 0
        self._pending_view_anchor = None
        self._view_cycle_available = False
        # Owned here so resolved_view() works before files-engine populates
        # them per subject; files-engine is the only writer afterwards.
        self._files_spread_pending = False
        self._files_spread_blocked = False

    # -- Policy storage -------------------------------------------------

    def view_policy(self, deck: DeckId) -> DeckView:
        """Return the stored policy for ``deck`` (other decks are AUTO)."""
        try:
            policies = self._view_policies
        except Exception:
            return DeckView.AUTO
        try:
            if deck is DeckId.MAIN:
                return policies.main
            if deck is DeckId.FILES:
                return policies.files
        except Exception:
            pass
        return DeckView.AUTO

    def sync_view_policies(self, policies: DeckViewPolicies) -> bool:
        """Store ``policies``; True when the shown deck's policy changed."""
        try:
            old = self._view_policies.for_deck(self._deck)
        except Exception:
            old = DeckView.AUTO
        try:
            self._view_policies = policies
        except Exception:
            return False
        try:
            return bool(policies.for_deck(self._deck) != old)
        except Exception:
            return False

    def set_view_policy(self, deck: DeckId, view: DeckView) -> None:
        """Store ``view`` for ``deck``, applying it when that deck is shown."""
        try:
            policies = self._view_policies
        except Exception:
            self._init_view_state()
            policies = self._view_policies
        # Raises ValueError for Tools and Files PAGE_BLOCKS, like the model.
        self._view_policies = policies.with_deck(deck, view)
        if deck is not self._deck:
            self._refresh_view_chrome()
            return
        if deck is DeckId.MAIN:
            try:
                document = self._main_document
            except Exception:
                document = None
            if (
                document is None
                or getattr(document, "partial", False)
                or not getattr(document, "cards", ())
            ):
                # Partial or empty: store only; the next full document
                # applies the policy through the normal deciders.
                self._refresh_view_chrome()
                return
            self._apply_main_view_change()
            return
        # FILES applies in files-engine; store and refresh chrome only.
        self._refresh_view_chrome()

    def _refresh_view_chrome(self) -> None:
        """Refresh chrome and cached predicates without raising."""
        try:
            self.refresh_chrome()
        except Exception:
            pass
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._sync_block_rail()
        except Exception:
            pass

    def _sync_block_navigable(self) -> None:
        """Refresh the block predicate, then the view-cycle predicate.

        Every panel path funnels through the block predicate sync, so
        overriding it here keeps the cached cycle predicate fresh without
        touching each call site.
        """
        try:
            parent = super()
            refresh = getattr(parent, "_sync_block_navigable", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass
        try:
            self._sync_view_cycle_available()
        except Exception:
            pass

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
            return _policy_next_view(
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
            from .view_policy import ResolvedView as _Resolved
            from .view_policy import ViewStatus

            return _Resolved(
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

    # -- View-change transition -----------------------------------------

    def _clear_pending_view_anchor(self, generation: int) -> None:
        """Drop the pending anchor once ``generation`` has settled."""
        try:
            pending = self._pending_view_anchor
        except Exception:
            return
        if pending is None:
            return
        try:
            _, _, pending_generation = pending
        except Exception:
            return
        if pending_generation != generation:
            return
        try:
            self._pending_view_anchor = None
        except Exception:
            pass

    def _scroll_main_to(self, target: int, generation: int) -> None:
        """Scroll the Main scroller when ``generation`` is still current."""
        if generation != self._view_generation:
            return
        try:
            scroll = self.query_one(
                f"#agent-deck-panel-{self._panel_index}-main-scroll",
                VerticalScroll,
            )
        except Exception:
            return
        try:
            scroll.scroll_to(y=max(0, int(target)), animate=False, immediate=True)
        except TypeError:
            try:
                scroll.scroll_to(y=max(0, int(target)), animate=False)
            except Exception:
                return
        except Exception:
            return
        try:
            self.call_after_refresh(lambda: sync_scrollbar_position(scroll))
        except Exception:
            pass

    def _spread_block_row(self, block_id: str) -> int | None:
        """Return the spread block-anchor row for ``block_id``."""
        try:
            view = self.main_view
        except Exception:
            return None
        try:
            width = int(view._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            width = 0
        if width <= 0:
            return None
        try:
            pairs = view.block_anchor_rows(width=width)
        except Exception:
            return None
        if not pairs:
            return None
        for bid, row in pairs:
            if bid == block_id:
                return int(row)
        return None

    def _restore_spread_view_target(self, anchor: Any, generation: int) -> None:
        """Restore a spread target with bounded, generation-guarded retries."""
        if anchor is None:
            return
        try:
            pinned = bool(anchor.pinned)
        except Exception:
            pinned = False
        if pinned:
            if generation != self._view_generation:
                return
            try:
                self.main_view.pin_to_bottom()
            except Exception:
                pass
            try:
                self.call_after_refresh(lambda: self._reapply_view_pin(generation))
            except Exception:
                pass
            self._clear_pending_view_anchor(generation)
            return
        try:
            block_id = anchor.block_id
            card_id = anchor.card_id
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            return
        if block_id is not None:
            self._restore_spread_block_offset(anchor, generation, 0)
            return
        try:
            base = self.main_view.spread_body_start(card_id or "") if card_id else None
        except Exception:
            base = None
        if base is None:
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_card_offset(anchor, generation, 1)
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(base) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _reapply_view_pin(self, generation: int) -> None:
        """Reapply a restored bottom pin after layout settles."""
        if generation != self._view_generation:
            return
        try:
            self.main_view.pin_to_bottom()
        except Exception:
            pass
        self._clear_pending_view_anchor(generation)

    def _restore_spread_card_offset(
        self, anchor: Any, generation: int, attempt: int
    ) -> None:
        """Retry a card-top spread restore with a bounded attempt count."""
        if generation != self._view_generation:
            return
        try:
            card_id = anchor.card_id
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            return
        try:
            base = self.main_view.spread_body_start(card_id or "") if card_id else None
        except Exception:
            base = None
        if base is None:
            if attempt >= 3:
                self._scroll_main_to(0, generation)
                self._clear_pending_view_anchor(generation)
                return
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_card_offset(
                        anchor, generation, attempt + 1
                    )
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(base) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _restore_spread_block_offset(
        self, anchor: Any, generation: int, attempt: int
    ) -> None:
        """Retry a block-anchored spread restore with a bounded count."""
        if generation != self._view_generation:
            # A newer view change owns the scroll position now.
            return
        try:
            offset = max(0, int(anchor.offset_rows))
            block_id = anchor.block_id
        except Exception:
            return
        row = self._spread_block_row(block_id) if block_id is not None else None
        if row is None:
            if attempt >= 3:
                # Anchors never published: fall back to the card top.
                try:
                    base = self.main_view.spread_body_start(anchor.card_id or "")
                except Exception:
                    base = None
                self._scroll_main_to(int(base) if base is not None else 0, generation)
                self._clear_pending_view_anchor(generation)
                return
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_block_offset(
                        anchor, generation, attempt + 1
                    )
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(row) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _restore_paged_view_target(
        self, anchor: Any, active: str | None, generation: int
    ) -> None:
        """Restore a paged target; stale generations are a no-op."""
        if generation != self._view_generation:
            return
        if anchor is None:
            return
        try:
            pinned = bool(anchor.pinned)
        except Exception:
            pinned = False
        if pinned:
            try:
                self.main_view.pin_to_bottom()
            except Exception:
                pass
            try:
                self.call_after_refresh(lambda: self._reapply_view_pin(generation))
            except Exception:
                pass
            self._clear_pending_view_anchor(generation)
            return
        try:
            has_block = anchor.block_id is not None and anchor.card_id is not None
        except Exception:
            has_block = False
        if has_block:
            # Staleness safety comes from the shared pending anchor: every
            # rapid change reuses it, so a stale deferred retry converges on
            # the same block target instead of a torn scroll offset.
            try:
                self._restore_block_transition(anchor, active)
            except Exception:
                pass
            try:
                self.call_after_refresh(
                    lambda: self._clear_pending_view_anchor(generation)
                )
            except Exception:
                pass
            return
        try:
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            offset = 0
        self._scroll_main_to(offset, generation)
        self._clear_pending_view_anchor(generation)

    def _apply_main_view_change(self) -> None:
        """Apply the stored Main policy, keeping the reader's place (D7)."""
        try:
            document = self._main_document
        except Exception:
            return
        try:
            subject = document.subject
            cards = document.cards
            partial = document.partial
        except Exception:
            return
        if partial or not cards:
            self._refresh_view_chrome()
            return
        try:
            old_mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
        except Exception:
            old_mode = RenderMode.PAGED
        # While a restore is still pending, reuse that anchor instead of
        # capturing from a scroll offset that has not been restored yet. A
        # subject change drops it (subjects never share anchors).
        anchor: Any = None
        try:
            pending = self._pending_view_anchor
        except Exception:
            pending = None
        if pending is not None:
            try:
                pending_subject, pending_anchor, _ = pending
                if pending_subject == subject and pending_anchor is not None:
                    anchor = pending_anchor
            except Exception:
                anchor = None
        if anchor is None:
            try:
                anchor = self._capture_reading_anchor(document, old_mode=old_mode)
            except Exception:
                anchor = None
        try:
            self._view_generation += 1
            generation = int(self._view_generation)
        except Exception:
            generation = 0
        try:
            self._pending_view_anchor = (subject, anchor, generation)
        except Exception:
            pass
        # A policy switch (including back to AUTO) decides both levels
        # without hysteresis, like a fresh Auto decision for this content.
        try:
            self._block_mode_key = None
        except Exception:
            pass
        try:
            new_mode = self._decide_main_mode(document, same_subject=False)
        except Exception:
            self._refresh_view_chrome()
            return
        try:
            self._render_mode[DeckId.MAIN] = new_mode
            self._mode_subject[DeckId.MAIN] = subject
        except Exception:
            pass
        try:
            current: str | None = self.main_view.active_card_id
        except Exception:
            current = None
        if current is None:
            try:
                current = self._main_active_card
            except Exception:
                current = None
        try:
            anchor_card: str | None = anchor.card_id if anchor is not None else None
        except Exception:
            anchor_card = None
        if new_mode is RenderMode.SPREAD:
            try:
                active = self.main_view.show_document(
                    document,
                    preferred_card=anchor_card or current,
                    mode=new_mode,
                )
            except TypeError:
                try:
                    active = self.main_view.show_document(
                        document, preferred_card=anchor_card or current
                    )
                except Exception:
                    active = None
            except Exception:
                active = None
            try:
                # The restore targets the anchor card, not the derived one.
                self._main_active_card = anchor_card or active
            except Exception:
                pass
            self._restore_spread_view_target(anchor, generation)
        else:
            target_card = anchor_card or current
            card_obj = None
            if target_card is not None:
                try:
                    card_obj = document.card(target_card)
                except Exception:
                    card_obj = None
            # Entering page blocks shows the anchor's block, not the newest:
            # align the cursor first, exactly as scroll-sync would have.
            try:
                policy = self.view_policy(DeckId.MAIN)
            except Exception:
                policy = DeckView.AUTO
            try:
                block_total = len(card_obj.blocks) if card_obj is not None else 0
            except Exception:
                block_total = 0
            try:
                want_paged_blocks = (
                    forced_block_mode(policy, block_total) is RenderMode.PAGED
                )
            except Exception:
                want_paged_blocks = False
            if want_paged_blocks and card_obj is not None and anchor is not None:
                try:
                    anchor_block = anchor.block_id
                except Exception:
                    anchor_block = None
                if (
                    anchor_block is not None
                    and card_obj.block(anchor_block) is not None
                ):
                    try:
                        cursor = self.main_view.active_block_id(target_card or "")
                    except Exception:
                        cursor = None
                    if cursor != anchor_block:
                        try:
                            self.main_view.select_block_cursor(card_obj, anchor_block)
                        except Exception:
                            pass
            # Same-subject view change: suppress the show-time block-spread
            # newest landing (it would fight the anchor restore, including
            # through its deferred retries) by presetting the projection
            # identity the show is about to compute. The restore below owns
            # the final scroll position and cursor.
            try:
                view_subject_seen = bool(self.main_view._subject_seen)  # type: ignore[attr-defined]
                view_subject = self.main_view._previous_subject  # type: ignore[attr-defined]
            except Exception:
                view_subject_seen = False
                view_subject = None
            if view_subject_seen and view_subject == subject and card_obj is not None:
                try:
                    navigable = bool(card_obj.has_block_navigation)
                except Exception:
                    navigable = False
                if navigable and want_paged_blocks is False:
                    try:
                        self.main_view._block_projected = (target_card, None)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            try:
                active = self._show_main_paged(document, target_card, new_mode)
            except Exception:
                active = None
            try:
                self._main_active_card = active
            except Exception:
                pass
            self._restore_paged_view_target(anchor, active, generation)
        try:
            self._sync_files_views()
        except Exception:
            pass
        self._refresh_view_chrome()
        # The chrome refresh above already re-synced the cycle predicate
        # through the block-predicate override; call it directly as well so
        # a missing override in a future MRO cannot leave it stale.
        try:
            self._sync_view_cycle_available()
        except Exception:
            pass
