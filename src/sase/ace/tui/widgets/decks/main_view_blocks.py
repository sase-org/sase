"""Block-paged projection state for ``MainDeckView``.

Each deck panel keeps one :class:`BlockCursor` per card for the current
subject on its pre-composed ``MainDeckView`` (panel-local, ephemeral, never
persisted). In paged deck mode a card with two or more blocks projects a
single block page; in block-spread (and with the flag off) the whole card
renders exactly as before.
"""

from __future__ import annotations

from typing import Any

from rich.console import Group
from textual.containers import VerticalScroll

from .block_model import (
    BlockCursor,
    arrived_ids,
    cycle_block_id,
    derive_spread_block,
    land_cursor,
    reconcile_cursor,
    select_cursor,
    step_cursor,
)
from .model import RenderMode


def _sync_scrollbar_position(scroll: VerticalScroll) -> None:
    """Pin ``scroll``'s thumb to its scroller, even while the bar is hidden.

    Textual only pushes ``scroll_y`` to ``ScrollBar.position`` while the bar
    is shown, and the layout shrink that hides the bar clamps ``scroll_y``
    first -- so a tall-to-short swap (block-spread to block-paged) can leave
    ``position`` stale at the old offset while the scroller sits at 0. The
    thumb then misrenders when the bar reappears, until the next explicit
    scroll. Syncing explicitly keeps the first settled frame converged
    without a synthetic scroll.
    """
    try:
        bar = scroll.vertical_scrollbar
    except Exception:
        return
    try:
        bar.position = float(scroll.scroll_y)
    except Exception:
        pass
    try:
        bar.refresh()
    except Exception:
        pass


class MainDeckViewBlocksMixin:
    """Per-card block cursors and block-page projection for Main views."""

    _block_cursors: dict[str, BlockCursor]
    _block_cursor_subject: object | None
    _block_modes: dict[str, RenderMode]
    _block_projected: tuple[str, str | None] | None

    def _init_block_view_state(self) -> None:
        self._block_cursors = {}
        self._block_cursor_subject = None
        self._block_modes = {}
        self._block_projected = None
        self._block_spread_pending: str | None = None
        self._block_spread_retry: int = 0

    def _reconcile_block_cursors(
        self, document: Any, *, new_subject: bool, enabled: bool
    ) -> None:
        """Reconcile every block card's cursor; clear them on subject change."""
        if not enabled or getattr(document, "partial", False):
            return
        if new_subject or self._block_cursor_subject != document.subject:
            self._block_cursors = {}
            self._block_modes = {}
            self._block_cursor_subject = document.subject
            new_subject = True
        else:
            # Drop cursors for cards that no longer exist.
            live = {card.card_id for card in document.cards}
            for card_id in list(self._block_cursors):
                if card_id not in live:
                    del self._block_cursors[card_id]
            for card_id in list(self._block_modes):
                if card_id not in live:
                    del self._block_modes[card_id]
        for card in document.cards:
            ids = card.block_ids if hasattr(card, "block_ids") else ()
            if len(ids) < 2:
                self._block_cursors.pop(card.card_id, None)
                continue
            cursor = self._block_cursors.get(card.card_id)
            try:
                landed = reconcile_cursor(ids, cursor, new_subject=new_subject)
            except Exception:
                landed = None
            if landed is None:
                self._block_cursors.pop(card.card_id, None)
            else:
                self._block_cursors[card.card_id] = landed

    def _block_cursor_for(self, card_id: str) -> BlockCursor | None:
        """Return the reconciled cursor for ``card_id``, if any."""
        try:
            return self._block_cursors.get(card_id)
        except Exception:
            return None

    def active_block_id(self, card_id: str) -> str | None:
        """Return the active block id for ``card_id``, if any."""
        cursor = self._block_cursor_for(card_id)
        return cursor.block_id if cursor is not None else None

    def arrived_block_ids(self, card_id: str) -> tuple[str, ...]:
        """Return unseen block ids for ``card_id`` (arrival dots)."""
        try:
            document = self._document  # type: ignore[attr-defined]
        except Exception:
            return ()
        card = document.card(card_id) if document is not None else None
        if card is None:
            return ()
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return ()
        try:
            return arrived_ids(ids, self._block_cursors.get(card_id))
        except Exception:
            return ()

    def block_mode_for_active_card(self) -> RenderMode | None:
        """Return the decided block mode for the active card, if any."""
        try:
            active = self._active_card  # type: ignore[attr-defined]
        except Exception:
            return None
        if active is None:
            return None
        try:
            return self._block_modes.get(active)
        except Exception:
            return None

    def _remember_block_mode(self, card_id: str, mode: RenderMode) -> None:
        try:
            self._block_modes[card_id] = mode
        except Exception:
            pass

    def step_block_cursor(self, card: Any, direction: int) -> BlockCursor | None:
        """Step ``card``'s cursor one block; None when not navigable."""
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return None
        if len(ids) < 2:
            return None
        try:
            current = self._block_cursors.get(card.card_id)
            stepped = step_cursor(ids, current, direction)
        except Exception:
            return None
        if stepped is None:
            return None
        try:
            self._block_cursors[card.card_id] = stepped
        except Exception:
            return None
        return stepped

    def select_block_cursor(
        self, card: Any, block_id: str | None
    ) -> BlockCursor | None:
        """Select ``block_id`` on ``card``; None when not navigable."""
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return None
        if len(ids) < 2:
            return None
        try:
            selected = select_cursor(ids, block_id)
        except Exception:
            return None
        if selected is None:
            return None
        try:
            self._block_cursors[card.card_id] = selected
        except Exception:
            return None
        return selected

    def _project_block_content(
        self,
        document: Any,
        card: Any,
        block_mode: RenderMode | None,
    ) -> tuple[Any, str | None, tuple[object, ...], str | None] | None:
        """Project ``card`` to one block page; None for the legacy render.

        Returns ``(renderable, digest, identity, block_id)`` where
        ``block_id`` is None for a whole-card block-spread projection.
        """
        if block_mode is None:
            return None
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return None
        if len(ids) < 2:
            return None
        digest = getattr(document, "digest", None)
        if block_mode is RenderMode.SPREAD:
            self._remember_block_mode(card.card_id, RenderMode.SPREAD)
            spread_digest = (
                None if digest is None else f"{digest}:{card.card_id}:spread"
            )
            return (
                Group(*card.renderables),
                spread_digest,
                (document.subject, card.card_id, "paged", "spread"),
                None,
            )
        cursor = self._block_cursors.get(card.card_id)
        if cursor is None or card.block(cursor.block_id) is None:
            return None
        self._remember_block_mode(card.card_id, RenderMode.PAGED)
        page = card.block_page(cursor.block_id)
        page_digest = (
            None if digest is None else f"{digest}:{card.card_id}:{cursor.block_id}"
        )
        return (
            Group(*page),
            page_digest,
            (document.subject, card.card_id, "paged", cursor.block_id),
            cursor.block_id,
        )

    def _scroll_main_to_top(self) -> None:
        """Reset the Main scroll to the top, ignoring unmounted state."""
        try:
            parent = self.parent  # type: ignore[attr-defined]
            if isinstance(parent, VerticalScroll):
                # Immediate so the watcher pushes position while the bar is
                # still shown; the deferred sync covers the layout shrink
                # that hides the bar before clamping scroll_y.
                parent.scroll_to(y=0, animate=False, immediate=True)
                try:
                    self.call_after_refresh(  # type: ignore[attr-defined]
                        lambda: _sync_scrollbar_position(parent)
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def land_block_cursor(self, card: Any) -> BlockCursor | None:
        """Land ``card`` on its newest block; None when not navigable."""
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return None
        if len(ids) < 2:
            return None
        try:
            landed = land_cursor(ids)
        except Exception:
            return None
        if landed is None:
            return None
        try:
            self._block_cursors[card.card_id] = landed
        except Exception:
            return None
        return landed

    def step_block_id_from(
        self, ids: tuple[str, ...], active: str | None, direction: int
    ) -> str | None:
        """Wrap :func:`cycle_block_id` for spread stepping with unknown anchors."""
        try:
            return cycle_block_id(list(ids), active, direction)
        except Exception:
            return None

    def block_header_row(self, block_id: str) -> int | None:
        """Return the BLOCK-anchor row for ``block_id``, if published."""
        try:
            width = int(self._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            return None
        if width <= 0:
            return None
        try:
            pairs = self.block_anchor_rows(width=width)  # type: ignore[attr-defined]
        except Exception:
            pairs = None
        if not pairs:
            return None
        for bid, row in pairs:
            if bid == block_id:
                return int(row)
        return None

    def _real_bottom(self) -> int | None:
        """Return the chat-log bottom excluding the layout reserve."""
        try:
            scroll = self.parent  # type: ignore[attr-defined]
            if not isinstance(scroll, VerticalScroll):
                return None
            return int(self.bottom_scroll_target(scroll))  # type: ignore[attr-defined]
        except Exception:
            return None

    def spread_landing_target(self, card: Any) -> int | None:
        """Return ``min(newest header, real bottom)`` for ``card``."""
        try:
            newest = card.newest_block_id
        except Exception:
            newest = None
        if newest is None:
            return None
        header = self.block_header_row(newest)
        bottom = self._real_bottom()
        if header is None or bottom is None:
            return None
        try:
            return min(int(header), int(bottom))
        except Exception:
            return None

    def scroll_to_block(self, block_id: str, *, _attempt: int = 0) -> bool:
        """Top-align ``block_id`` with the block-aware reserve (bounded retry)."""
        try:
            self.enable_section_layout_reserve(include_blocks=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        row = self.block_header_row(block_id)
        if row is None:
            if _attempt >= 3:
                return False
            try:
                self._block_spread_pending = block_id
                self._block_spread_retry = _attempt
                self.call_after_refresh(  # type: ignore[attr-defined]
                    lambda: self.scroll_to_block(block_id, _attempt=_attempt + 1)
                )
            except Exception:
                pass
            return False
        try:
            scroll = self.parent  # type: ignore[attr-defined]
            if isinstance(scroll, VerticalScroll):
                scroll.scroll_to(y=int(row), animate=False)
                try:
                    self._block_spread_pending = None
                    self._block_spread_retry = 0
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False

    def land_block_spread(self, card: Any) -> bool:
        """Chat-log landing for a block-spread card; True when applied/scheduled."""
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return False
        if len(ids) < 2:
            return False
        newly_enabled = False
        try:
            newly_enabled = bool(
                self.enable_section_layout_reserve(include_blocks=True)  # type: ignore[attr-defined]
            )
        except Exception:
            newly_enabled = False
        try:
            self.land_block_cursor(card)
        except Exception:
            pass
        try:
            newest = card.newest_block_id
        except Exception:
            newest = None
        if newest is None:
            return False
        # Same-cycle fast path avoids a flash of the oldest block, but only
        # when the reserve was already enabled: a just-enabled reserve has
        # not applied to layout yet, so its real-bottom math is stale.
        if not newly_enabled:
            target = self.spread_landing_target(card)
            if target is not None:
                try:
                    scroll = self.parent  # type: ignore[attr-defined]
                    if isinstance(scroll, VerticalScroll):
                        scroll.scroll_to(y=int(target), animate=False)
                        return True
                except Exception:
                    pass
        # Anchors or reserve not ready yet: bounded deferred retry until they
        # publish and layout settles.
        try:
            self._block_spread_pending = newest
            self._block_spread_retry = 0
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._apply_block_spread_landing(card.card_id, 0)
            )
        except Exception:
            return False
        return True

    def _apply_block_spread_landing(self, card_id: str, attempt: int) -> None:
        if attempt >= 3:
            try:
                self._block_spread_pending = None
            except Exception:
                pass
            return
        try:
            document = self._document  # type: ignore[attr-defined]
        except Exception:
            document = None
        card = None
        try:
            card = document.card(card_id) if document is not None else None
        except Exception:
            card = None
        if card is None:
            return
        target = self.spread_landing_target(card)
        if target is None:
            try:
                self.call_after_refresh(  # type: ignore[attr-defined]
                    lambda: self._apply_block_spread_landing(card_id, attempt + 1)
                )
            except Exception:
                pass
            return
        try:
            scroll = self.parent  # type: ignore[attr-defined]
            if isinstance(scroll, VerticalScroll):
                scroll.scroll_to(y=int(target), animate=False)
        except Exception:
            pass
        # The trailing reserve converges over several layout/paint cycles:
        # re-verify once the reserve has applied so an early header target
        # cannot leave a blank tail.
        if attempt < 2:
            try:
                self.call_after_refresh(  # type: ignore[attr-defined]
                    lambda: self._apply_block_spread_landing(card_id, attempt + 1)
                )
            except Exception:
                pass
            return
        try:
            self._block_spread_pending = None
            self._block_spread_retry = 0
        except Exception:
            pass

    def derive_spread_cursor(self, card: Any) -> str | None:
        """Derive the scroll block for ``card`` in a spread rendering."""
        try:
            width = int(self._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            return None
        if width <= 0:
            return None
        try:
            pairs = self.block_anchor_rows(width=width)  # type: ignore[attr-defined]
        except Exception:
            pairs = None
        if not pairs:
            return None
        try:
            scroll = self.parent  # type: ignore[attr-defined]
            scroll_y = float(scroll.scroll_y) if scroll is not None else 0.0
        except Exception:
            scroll_y = 0.0
        try:
            at_bottom = False
            scroll_obj = self.parent  # type: ignore[attr-defined]
            if isinstance(scroll_obj, VerticalScroll):
                at_bottom = float(scroll_obj.scroll_y) >= float(
                    self.bottom_scroll_target(scroll_obj)  # type: ignore[attr-defined]
                )
        except Exception:
            at_bottom = False
        try:
            return derive_spread_block(
                pairs, scroll_y=scroll_y, at_real_bottom=at_bottom
            )
        except Exception:
            return None

    def sync_spread_cursor_from_scroll(self, card: Any) -> BlockCursor | None:
        """Recompute ``card``'s cursor from scroll; None when not derivable.

        Staying on the same block preserves ``known_ids`` so a layout-driven
        scroll shift on streaming growth cannot silently clear arrival dots;
        only a scroll to a different block selects (marking all seen).
        """
        derived = self.derive_spread_cursor(card)
        # Above the first header derives None: no selection (stays put).
        if derived is None:
            return None
        try:
            ids = tuple(card.block_ids)
        except Exception:
            return None
        if len(ids) < 2 or derived not in set(ids):
            return None
        try:
            current = self._block_cursors.get(card.card_id)
        except Exception:
            current = None
        if current is not None and derived == current.block_id:
            return None
        try:
            selected = select_cursor(ids, derived)
        except Exception:
            return None
        if selected is None:
            return None
        try:
            self._block_cursors[card.card_id] = selected
        except Exception:
            return None
        return selected


__all__ = ["MainDeckViewBlocksMixin"]
