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
    reconcile_cursor,
    select_cursor,
    step_cursor,
)
from .model import RenderMode


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
                parent.scroll_to(y=0, animate=False)
        except Exception:
            pass


__all__ = ["MainDeckViewBlocksMixin"]
