"""Hierarchical reading anchors for deck and block mode transitions.

One :class:`_ReadingAnchor` captures ``(card_id, block_id, offset_rows,
pinned)`` before a spread/paged recomposition and restores the most
specific target that survives: same block + offset (clamped >= 0), then
card top, then card default, then document default. With
``block_id=None`` the restore reproduces the pre-block transition math
exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.containers import VerticalScroll

from .block_model import derive_spread_block
from .main_view_blocks import _sync_scrollbar_position
from .model import DeckId, RenderMode

__all__ = [
    "DeckPanelTransitionsMixin",
]


@dataclass(frozen=True, slots=True)
class _ReadingAnchor:
    """Hierarchical reading position across deck/block transitions."""

    card_id: str | None
    block_id: str | None
    offset_rows: int
    pinned: bool


def _main_scroll(panel: Any) -> VerticalScroll | None:
    try:
        return panel.query_one(
            f"#agent-deck-panel-{panel._panel_index}-main-scroll",
            VerticalScroll,
        )
    except Exception:
        return None


def _scroll_y(panel: Any) -> int:
    try:
        scroll = _main_scroll(panel)
        if scroll is not None:
            return int(scroll.scroll_y)
    except Exception:
        pass
    return 0


def _is_pinned(panel: Any) -> bool:
    try:
        return bool(getattr(panel.main_view, "is_pinned_to_bottom", False))
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


def _block_row(panel: Any, block_id: str) -> int | None:
    try:
        view = panel.main_view
    except Exception:
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


def _at_real_bottom(panel: Any) -> bool:
    try:
        view = panel.main_view
        scroll = _main_scroll(panel)
        if scroll is None:
            return False
        target = int(view.bottom_scroll_target(scroll))
        return _scroll_y(panel) >= target
    except Exception:
        return False


def _capture_panel_anchor(
    panel: Any, document: Any, *, old_mode: RenderMode
) -> _ReadingAnchor:
    """Capture the hierarchical reading position before recomposition."""
    scroll_y = _scroll_y(panel)
    pinned = _is_pinned(panel)
    card_id: str | None = None
    try:
        if old_mode is RenderMode.SPREAD:
            card_id = panel._main_spread_active() or panel._main_active_card
        else:
            try:
                card_id = panel.main_view.active_card_id
            except Exception:
                card_id = None
            if card_id is None:
                card_id = getattr(panel, "_main_active_card", None)
    except Exception:
        card_id = getattr(panel, "_main_active_card", None)
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
                view = panel.main_view
                width = int(view._spread_content_width())
                pairs = view.block_anchor_rows(width=width) if width > 0 else None
                if pairs:
                    derived = derive_spread_block(
                        pairs,
                        scroll_y=float(scroll_y),
                        at_real_bottom=_at_real_bottom(panel),
                    )
                if derived is None:
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
                row = _block_row(panel, derived)
                if row is not None:
                    offset = max(0, scroll_y - row)
                else:
                    offset = 0
                return _ReadingAnchor(
                    card_id=card_id,
                    block_id=block_id,
                    offset_rows=max(0, int(offset)),
                    pinned=pinned,
                )
        # No block anchor: today's spread math.
        try:
            body_start = panel.main_view.spread_body_start(card_id or "")
        except Exception:
            body_start = None
        if body_start is not None:
            offset = max(0, scroll_y - int(body_start))
        else:
            # Paged-origin offsets keep the raw scroll_y; spread-origin
            # offsets without a body start collapse to the card top.
            offset = 0 if old_mode is RenderMode.SPREAD else int(scroll_y)
        return _ReadingAnchor(
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
                block_mode = panel.main_view.block_mode_for_active_card()
            except Exception:
                block_mode = None
            if block_mode is RenderMode.SPREAD:
                try:
                    view = panel.main_view
                    width = int(view._spread_content_width())
                    pairs = view.block_anchor_rows(width=width) if width > 0 else None
                    if pairs:
                        candidate = derive_spread_block(
                            pairs,
                            scroll_y=float(scroll_y),
                            at_real_bottom=_at_real_bottom(panel),
                        )
                except Exception:
                    candidate = None
                if candidate is None or card.block(candidate) is None:
                    try:
                        candidate = panel.main_view.active_block_id(card.card_id)
                    except Exception:
                        candidate = None
            else:
                try:
                    candidate = panel.main_view.active_block_id(card.card_id)
                except Exception:
                    candidate = None
            if candidate is not None and card.block(candidate) is not None:
                block_id = candidate
                row = _block_row(panel, candidate)
                if row is not None:
                    offset = max(0, scroll_y - row)
                else:
                    # Block-paged pages start at the top; the intra-page
                    # offset is the scroll position itself.
                    offset = max(0, int(scroll_y))
                return _ReadingAnchor(
                    card_id=card_id,
                    block_id=block_id,
                    offset_rows=max(0, int(offset)),
                    pinned=pinned,
                )
    # Today's paged math: the PAGED->SPREAD offset is the raw scroll_y and
    # is restored against the spread body start by the caller.
    offset = max(0, int(scroll_y))
    return _ReadingAnchor(
        card_id=card_id, block_id=None, offset_rows=offset, pinned=pinned
    )


def _synced_block_scroll_to(panel: Any, target: int) -> None:
    """Scroll ``panel``'s Main scroller and pin its scrollbar thumb.

    The scroll is immediate so ``ScrollBar.position`` tracks the scroller
    while the bar is still shown; the deferred sync covers the layout shrink
    that hides the bar before clamping ``scroll_y`` (the block-spread to
    block-paged stale-thumb race).
    """
    try:
        scroll = _main_scroll(panel)
        if scroll is not None:
            scroll.scroll_to(y=target, animate=False, immediate=True)
            try:
                panel.call_after_refresh(lambda: _sync_scrollbar_position(scroll))
            except Exception:
                pass
    except Exception:
        pass


def _restore_block_offset(
    panel: Any, anchor: _ReadingAnchor, *, fallback_target: int = 0
) -> None:
    """Scroll to ``block row + offset`` with a bounded post-layout retry."""

    def _apply(attempt: int) -> None:
        row = (
            _block_row(panel, anchor.block_id) if anchor.block_id is not None else None
        )
        if row is None:
            if attempt >= 3:
                # The block anchor never published: fall back to the
                # card top so the reader is not left at an unrelated offset.
                _synced_block_scroll_to(panel, max(0, fallback_target))
                return
            try:
                panel.call_after_refresh(lambda: _apply(attempt + 1))
            except Exception:
                pass
            return
        target = max(0, int(row) + max(0, int(anchor.offset_rows)))
        _synced_block_scroll_to(panel, target)

    try:
        # Same-cycle fast path: anchors already cached, no flash of the
        # oldest block.
        row = (
            _block_row(panel, anchor.block_id) if anchor.block_id is not None else None
        )
        if row is not None:
            target = max(0, int(row) + max(0, int(anchor.offset_rows)))
            _synced_block_scroll_to(panel, target)
            return
        panel.call_after_refresh(lambda: _apply(0))
    except Exception:
        pass


class DeckPanelTransitionsMixin:
    """Deck spread/paged transitions with hierarchical reading anchors."""

    _panel_index: int
    _main_active_card: str | None

    def _capture_reading_anchor(
        self, document: Any, *, old_mode: RenderMode
    ) -> _ReadingAnchor:
        return _capture_panel_anchor(self, document, old_mode=old_mode)

    def _preferred_card_from_area(self) -> str | None:
        preferred: str | None = None
        try:
            node: Any | None = getattr(self, "parent", None)
            for _ in range(5):
                if node is None:
                    break
                state = getattr(node, "_state", None)
                if state is not None:
                    try:
                        preferred = state.panels[self._panel_index].preferred_card  # type: ignore[attr-defined]
                    except Exception:
                        preferred = None
                    break
                node = getattr(node, "parent", None)
        except Exception:
            preferred = None
        return preferred

    def _refresh_main_mode_for_shown(self) -> None:
        document = self._main_document  # type: ignore[attr-defined]
        if not document.cards or document.partial:
            return
        stored = self._mode_subject.get(DeckId.MAIN)  # type: ignore[attr-defined]
        same = stored is not None and stored == document.subject
        new_mode = self._decide_main_mode(document, same_subject=same)  # type: ignore[attr-defined]
        old_mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)  # type: ignore[attr-defined]
        if new_mode is old_mode:
            # Deck mode is stable, but the block mode may be stale
            # (unmeasured first paint, resize, split or header toggles).
            # A block spread<->paged flip keeps the reader's block and
            # offset via one hierarchical anchor.
            try:
                if new_mode is RenderMode.PAGED and self._needs_block_refresh():  # type: ignore[attr-defined]
                    anchor = self._capture_reading_anchor(document, old_mode=old_mode)
                    active = self._show_main_paged(  # type: ignore[attr-defined]
                        document,
                        self._main_active_card,
                        new_mode,  # type: ignore[attr-defined]
                    )
                    self._main_active_card = active  # type: ignore[attr-defined]
                    try:
                        self._restore_block_transition(anchor, active)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                self._sync_block_navigable()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        preferred = self._preferred_card_from_area()
        # Avoid recursion via set_deck: apply directly.
        self._render_mode[DeckId.MAIN] = new_mode  # type: ignore[attr-defined]
        self._mode_subject[DeckId.MAIN] = document.subject  # type: ignore[attr-defined]
        try:
            if new_mode is RenderMode.SPREAD:
                self.main_view.show_document(  # type: ignore[attr-defined]
                    document, preferred_card=preferred, mode=new_mode
                )
                if (
                    preferred is not None
                    and document.card(preferred) is not None
                    and preferred
                    != (document.cards[0].card_id if document.cards else None)
                ):
                    try:
                        self.main_view.scroll_to_card(preferred)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    # Deck-spread sticky landing for the preferred block card.
                    try:
                        landed = self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                            document, preferred
                        )
                        if landed:
                            self._main_active_card = self.main_view.active_card_id  # type: ignore[attr-defined]
                            return
                    except Exception:
                        pass
                self._main_active_card = self.main_view.active_card_id  # type: ignore[attr-defined]
            else:
                spread_active = self._main_spread_active() or self._main_active_card  # type: ignore[attr-defined,operator]
                transition_anchor: _ReadingAnchor | None = None
                try:
                    transition_anchor = self._capture_reading_anchor(
                        document, old_mode=old_mode
                    )
                    if transition_anchor.block_id is not None:
                        spread_active = transition_anchor.card_id or spread_active
                except Exception:
                    transition_anchor = None
                active = self._show_main_paged(  # type: ignore[attr-defined]
                    document, spread_active or preferred, new_mode
                )
                self._main_active_card = active  # type: ignore[attr-defined]
                if (
                    transition_anchor is not None
                    and transition_anchor.block_id is not None
                ):
                    try:
                        self._restore_block_transition(transition_anchor, active)  # type: ignore[attr-defined]
                    except Exception:
                        pass
        except Exception:
            pass
        self._sync_files_views()  # type: ignore[attr-defined]
        self.refresh_chrome()  # type: ignore[attr-defined]
        try:
            self._sync_block_navigable()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _restore_block_transition(
        self, anchor: _ReadingAnchor, active: str | None
    ) -> None:
        """Restore a block-anchored position after a mode recomposition."""
        if anchor.pinned:
            try:
                self.main_view.pin_to_bottom()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if anchor.block_id is None or anchor.card_id is None:
            return
        try:
            document = self._main_document  # type: ignore[attr-defined]
        except Exception:
            return
        card = _card_with_blocks(document, anchor.card_id)
        if card is None or card.block(anchor.block_id) is None:
            return
        if active is not None and active != anchor.card_id:
            return
        # Offsets clamp at 0, so a bottom-landed newest block becomes the
        # newest page's top.
        _restore_block_offset(self, anchor, fallback_target=0)

    def _apply_main_transition(
        self,
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
                f"#agent-deck-panel-{self._panel_index}-main-scroll",
                VerticalScroll,
            )
            scroll_y = int(scroll.scroll_y)
        except Exception:
            scroll = None
        try:
            pinned = bool(getattr(self.main_view, "is_pinned_to_bottom", False))  # type: ignore[attr-defined]
        except Exception:
            pinned = False
        anchor_card: str | None = None
        offset = 0
        anchor: _ReadingAnchor | None = None
        try:
            anchor = self._capture_reading_anchor(document, old_mode=old_mode)
        except Exception:
            anchor = None
        if anchor is not None and anchor.block_id is not None:
            anchor_card = anchor.card_id
            offset = anchor.offset_rows
            pinned = anchor.pinned
        elif old_mode is RenderMode.SPREAD and new_mode is RenderMode.PAGED:
            anchor_card = self._main_spread_active() or self._main_active_card  # type: ignore[attr-defined,operator]
            try:
                body_start = self.main_view.spread_body_start(anchor_card or "")  # type: ignore[attr-defined]
            except Exception:
                body_start = None
            if body_start is not None:
                offset = max(0, scroll_y - body_start)
            else:
                offset = 0
        elif old_mode is RenderMode.PAGED and new_mode is RenderMode.SPREAD:
            anchor_card = self._main_active_card  # type: ignore[attr-defined]
            offset = scroll_y
        try:
            if new_mode is RenderMode.SPREAD:
                active = self.main_view.show_document(  # type: ignore[attr-defined]
                    document, preferred_card=preferred_card, mode=new_mode
                )
            else:
                active = self._show_main_paged(  # type: ignore[attr-defined]
                    document,
                    anchor_card or preferred_card,
                    new_mode,
                )
        except Exception:
            active = None
        self._main_active_card = active  # type: ignore[attr-defined]
        if new_mode is RenderMode.SPREAD:
            if (
                preferred_card is not None
                and document.card(preferred_card) is not None
                and preferred_card
                != (document.cards[0].card_id if document.cards else None)
            ):
                try:
                    self.main_view.scroll_to_card(preferred_card)  # type: ignore[attr-defined]
                    self._main_active_card = preferred_card  # type: ignore[attr-defined]
                except Exception:
                    pass
                return self._main_active_card  # type: ignore[attr-defined]
            # Sticky-Reply landing replaces the top start when the
            # preferred card carries blocks.
            try:
                landed = self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                    document, preferred_card
                )
                if landed:
                    return self._main_active_card  # type: ignore[attr-defined]
            except Exception:
                pass
            return self._main_active_card  # type: ignore[attr-defined]
        if pinned:
            try:
                self.main_view.pin_to_bottom()  # type: ignore[attr-defined]
            except Exception:
                pass
            return self._main_active_card  # type: ignore[attr-defined]
        # Anchor the reading position after layout settles.
        try:
            if anchor is not None and anchor.block_id is not None:
                self._restore_block_transition(anchor, active)
                return self._main_active_card  # type: ignore[attr-defined]
            if new_mode is RenderMode.PAGED:
                target = max(0, offset)

                def _restore_paged() -> None:
                    try:
                        sc = self.query_one(  # type: ignore[attr-defined]
                            f"#agent-deck-panel-{self._panel_index}-main-scroll",
                            VerticalScroll,
                        )
                        sc.scroll_to(y=target, animate=False)
                    except Exception:
                        pass

                self.call_after_refresh(_restore_paged)  # type: ignore[attr-defined]
            else:
                base = anchor_card or (active or "")
                body = self.main_view.spread_body_start(base) if base else None  # type: ignore[attr-defined]
                target_spread = (body or 0) + offset

                def _restore_spread() -> None:
                    row = self.main_view.spread_body_start(base) if base else None  # type: ignore[attr-defined]
                    target = (row or 0) + offset if row is not None else target_spread
                    try:
                        sc = self.query_one(  # type: ignore[attr-defined]
                            f"#agent-deck-panel-{self._panel_index}-main-scroll",
                            VerticalScroll,
                        )
                        sc.scroll_to(y=target, animate=False)
                    except Exception:
                        pass

                self.call_after_refresh(_restore_spread)  # type: ignore[attr-defined]
        except Exception:
            pass
        return self._main_active_card  # type: ignore[attr-defined]
