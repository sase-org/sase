"""Delivery-scoped spread selection hold for card-document views.

A same-subject background re-delivery re-renders a spread document. Its
layout can clamp ``scroll_y``, and the follow re-land or sticky chat-log
landing that accompanies it scrolls programmatically. None of those scrolls
is the reader choosing a card, yet the spread scroll watcher derives the
here-card from ``scroll_y`` (for example, a short Reply landed at row 0
derives the Context card above it).

The hold records which card the delivery must preserve, restores a parked
reader's anchor-relative offset once the new anchors publish, and releases
after layout settles. It is bound to one claim token: explicit navigation
(:meth:`release_spread_hold`), a new subject, a mode change, or a later
claim supersedes it, and a bounded check budget releases it even if layout
never converges. Every check is synchronous, O(anchors), and free of I/O.
"""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll

from .block_model import SpreadFollowState
from .model import RenderMode

#: Refresh checks before a hold releases even without settling.
_HOLD_MAX_CHECKS = 12
#: Consecutive quiet checks that prove the delivery's layout has settled.
_HOLD_QUIET_CHECKS = 2


class CardDocumentDeliveryHoldMixin:
    """Hold a spread card selection through one background delivery."""

    _hold_card: str | None
    _hold_token: int
    _hold_restore: tuple[str, int] | None
    _hold_restore_target: int | None
    _hold_checks: int
    _hold_quiet: int
    _hold_extent_retried: bool
    _hold_follow_state: SpreadFollowState | None
    _follow_seen: SpreadFollowState | None

    def _init_delivery_hold_state(self) -> None:
        self._hold_card = None
        self._hold_token = 0
        self._hold_restore = None
        self._hold_restore_target = None
        self._hold_checks = 0
        self._hold_quiet = 0
        self._hold_extent_retried = False
        self._hold_follow_state = None
        self._follow_seen = None

    @property
    def delivery_hold_card(self) -> str | None:
        """Return the card a background delivery is holding, if any."""
        return self._hold_card

    @property
    def delivery_restore_pending(self) -> bool:
        """Whether a parked reader's offset is still waiting to be restored."""
        return self._hold_restore is not None

    @property
    def delivery_restore_follow_state(self) -> SpreadFollowState | None:
        """Return the follow classification taken before the pending restore."""
        return self._hold_follow_state if self._hold_restore is not None else None

    def record_spread_follow_state(self, state: SpreadFollowState | None) -> None:
        """Remember the latest pre-delivery follow classification."""
        self._follow_seen = state

    def hold_spread_selection(
        self, card_id: str, *, restore_offset: int | None = None
    ) -> None:
        """Hold ``card_id`` until this delivery's layout settles.

        ``restore_offset`` is the reader's row relative to the card's spread
        anchor before the delivery; ``None`` leaves the scroll to its current
        owner (a follow landing, the bottom pin, or the unchanged offset).
        """
        self._hold_token += 1
        self._hold_card = card_id
        self._hold_restore = (
            None if restore_offset is None else (card_id, int(restore_offset))
        )
        # A restore keeps the reader where this delivery classified them; a
        # later delivery before it applies reuses that classification.
        self._hold_follow_state = (
            self._follow_seen if self._hold_restore is not None else None
        )
        self._follow_seen = None
        self._hold_restore_target = None
        self._hold_checks = 0
        self._hold_quiet = 0
        self._hold_extent_retried = False
        self._schedule_hold_check(self._hold_token)

    def release_spread_hold(self) -> None:
        """Release the hold now (explicit navigation, subject or mode change)."""
        self._follow_seen = None
        if self._hold_card is None and self._hold_restore is None:
            return
        self._hold_token += 1
        self._hold_card = None
        self._hold_restore = None
        self._hold_restore_target = None
        self._hold_checks = 0
        self._hold_quiet = 0
        self._hold_extent_retried = False
        self._hold_follow_state = None
        self._follow_seen = None

    def spread_reader_offset(self, card_id: str) -> int | None:
        """Return the scroll row relative to ``card_id``'s anchor, if measurable."""
        try:
            anchor = self.spread_anchor_row(card_id)  # type: ignore[attr-defined]
        except Exception:
            anchor = None
        if anchor is None:
            return None
        scroll = self._hold_scroll()
        if scroll is None:
            return None
        try:
            return int(scroll.scroll_y) - int(anchor)
        except Exception:
            return None

    def carried_spread_restore(self, card_id: str) -> int | None:
        """Return a not-yet-applied restore offset for ``card_id``.

        A second delivery that lands before the first restore applied must
        carry the original offset: the live scroll position is still the
        clamped or stale one.
        """
        restore = self._hold_restore
        if restore is None or restore[0] != card_id:
            return None
        return restore[1]

    def _hold_scroll(self) -> VerticalScroll | None:
        parent = getattr(self, "parent", None)
        return parent if isinstance(parent, VerticalScroll) else None

    def _schedule_hold_check(self, token: int) -> None:
        try:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._check_spread_hold(token)
            )
        except Exception:
            self.release_spread_hold()

    def _check_spread_hold(self, token: int) -> None:
        if token != self._hold_token or self._hold_card is None:
            return
        self._hold_checks += 1
        if self._hold_checks > _HOLD_MAX_CHECKS:
            self._finish_spread_hold()
            return
        if not self._hold_still_owned():
            self.release_spread_hold()
            return
        if not self._hold_anchors_ready():
            self._hold_quiet = 0
            self._schedule_hold_check(token)
            return
        if self._hold_restore is not None:
            self._apply_spread_restore()
            self._hold_quiet = 0
            self._schedule_hold_check(token)
            return
        if getattr(self, "_block_spread_pending", None) is not None:
            # A follow landing is still converging; it owns the scroll.
            self._hold_quiet = 0
            self._schedule_hold_check(token)
            return
        self._hold_quiet += 1
        if self._hold_quiet >= _HOLD_QUIET_CHECKS:
            self._finish_spread_hold()
            return
        self._schedule_hold_check(token)

    def _hold_still_owned(self) -> bool:
        if getattr(self, "_render_mode", None) is not RenderMode.SPREAD:
            return False
        if getattr(self, "_spread_pending_card", None) is not None:
            return False
        document: Any = getattr(self, "_document", None)
        try:
            return document is not None and document.card(self._hold_card) is not None
        except Exception:
            return False

    def _hold_anchors_ready(self) -> bool:
        try:
            width = int(self._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            return False
        if width <= 0:
            return False
        try:
            return self.card_anchor_rows(width=width) is not None  # type: ignore[attr-defined]
        except Exception:
            return False

    def _apply_spread_restore(self) -> None:
        """Restore the reader's anchor-relative row once (never fights later scrolls)."""
        restore = self._hold_restore
        scroll = self._hold_scroll()
        if restore is None or scroll is None:
            self._hold_restore = None
            return
        card_id, offset = restore
        try:
            anchor = self.spread_anchor_row(card_id)  # type: ignore[attr-defined]
        except Exception:
            anchor = None
        if anchor is None:
            self._hold_restore = None
            return
        desired = max(0, int(anchor) + int(offset))
        try:
            max_y = int(scroll.max_scroll_y)
        except Exception:
            max_y = desired
        if desired > max_y and not self._hold_extent_retried:
            # The trailing reserve can lag the first published layout by one
            # pass; remeasure once before clamping the reader's row.
            self._hold_extent_retried = True
            try:
                self.refresh_section_layout_reserve()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        target = max(0, min(desired, max_y))
        self._hold_restore = None
        self._hold_restore_target = target
        try:
            if int(scroll.scroll_y) == target:
                return
        except Exception:
            pass
        try:
            self._request_spread_scroll_y(target)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _finish_spread_hold(self) -> None:
        """Release a settled hold; re-derive if the reader scrolled meanwhile."""
        target = self._hold_restore_target
        moved = False
        if target is not None:
            scroll = self._hold_scroll()
            try:
                moved = scroll is not None and int(scroll.scroll_y) != int(target)
            except Exception:
                moved = False
        self.release_spread_hold()
        if not moved:
            return
        try:
            parent = getattr(self, "parent", None)
            panel = getattr(parent, "parent", None) if parent is not None else None
            notify = getattr(panel, "spread_hold_released", None)
            if callable(notify):
                notify(getattr(self, "_deck", None))
        except Exception:
            pass


__all__ = ["CardDocumentDeliveryHoldMixin"]
