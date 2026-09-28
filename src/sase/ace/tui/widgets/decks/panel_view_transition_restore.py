"""Anchor and scroll restores for the Main view-change transition.

Restore first of :mod:`sase.ace.tui.widgets.decks.panel_view_transition`:
the generation-guarded scroll helper, the pending-anchor bookkeeping, and
the spread/paged restore targets that keep the reader's card, block,
offset, pin, and following in every direction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll

from .main_view_blocks import sync_scrollbar_position

__all__ = ["DeckPanelViewRestoreMixin"]


class DeckPanelViewRestoreMixin:
    """Generation-guarded anchor restores for spread and paged targets."""

    _panel_index: int
    _view_generation: int
    _pending_view_anchor: tuple[object, Any, int] | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

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
