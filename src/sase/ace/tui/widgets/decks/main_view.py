"""Main deck card view inside a deck panel scroll."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..prompt_panel._section_view import SectionViewMixin
from .main_document import MainDeckDocument
from .model import RenderMode, resolve_active_card


class MainDeckView(SectionViewMixin, Static):
    """One Main card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Main deck view."""
        super().__init__(**kwargs)
        self._document: MainDeckDocument | None = None
        self._active_card: str | None = None
        self._last_render_key: tuple[object, ...] | None = None
        self._previous_subject: object | None = None
        self._subject_seen: bool = False
        self._render_mode: RenderMode = RenderMode.PAGED
        self._spread_pending_card: str | None = None
        self._spread_retry_count: int = 0

    @property
    def active_card_id(self) -> str | None:
        """Return the active card id."""
        return self._active_card

    @property
    def render_mode(self) -> RenderMode:
        """Return the current Main render mode."""
        return self._render_mode

    def _scroll_container(self) -> VerticalScroll | None:
        parent = self.parent
        return parent if isinstance(parent, VerticalScroll) else None

    def _spread_content_width(self) -> int:
        try:
            scroll = self._scroll_container()
            if scroll is not None:
                width = int(scroll.scrollable_content_region.width)
                if width > 0:
                    return width
        except Exception:
            pass
        try:
            width = int(self.size.width)
            if width > 0:
                return width
        except Exception:
            pass
        return 0

    def spread_active_card(self) -> str | None:
        """Return the spread active card from scroll, or first while not ready."""
        document = self._document
        if document is None or not document.cards:
            return None
        first_id = document.cards[0].card_id
        width = self._spread_content_width()
        if width <= 0:
            return first_id
        try:
            pairs = self.card_anchor_rows(width=width)
        except Exception:
            pairs = None
        if not pairs:
            return first_id
        try:
            scroll = self._scroll_container()
            scroll_y = int(scroll.scroll_y) if scroll is not None else 0
        except Exception:
            scroll_y = 0
        # First card anchor is implicitly row 0; prepend it.
        ordered = [
            (first_id, 0),
            *[(cid, row) for cid, row in pairs if cid != first_id],
        ]
        # Deduplicate keeping first occurrence order sorted by row.
        seen: set[str] = set()
        deduped: list[tuple[str, int]] = []
        for cid, row in sorted(ordered, key=lambda item: item[1]):
            if cid in seen:
                continue
            seen.add(cid)
            deduped.append((cid, row))
        active: str | None = None
        for cid, row in deduped:
            if row <= scroll_y:
                active = cid
            else:
                break
        return active or first_id

    def spread_body_start(self, card_id: str) -> int | None:
        """Return the body start row for ``card_id`` in spread mode."""
        document = self._document
        if document is None or not document.cards:
            return None
        if document.cards[0].card_id == card_id:
            return 0
        width = self._spread_content_width()
        if width <= 0:
            return None
        try:
            pairs = self.card_anchor_rows(width=width)
        except Exception:
            return None
        if not pairs:
            return None
        for cid, row in pairs:
            if cid == card_id:
                return row + 1
        return None

    def show_card(self, card_id: str) -> str | None:
        """Activate ``card_id`` from the stored document; return it or None."""
        document = self._document
        if document is None:
            return None
        card = document.card(card_id)
        if card is None:
            return None
        if self._render_mode is RenderMode.SPREAD:
            return self.scroll_to_card(card_id)
        self.prepare_section_document((document.subject, card_id, "paged"))
        try:
            parent = self.parent
            if isinstance(parent, VerticalScroll):
                parent.scroll_to(y=0, animate=False)
        except Exception:
            pass
        renderable: Any = Group(*card.renderables)
        digest = None if document.digest is None else f"{document.digest}:{card_id}"
        self._apply_section_content(renderable, digest, layout=True)
        self._active_card = card_id
        self._last_render_key = (document.digest, card_id, document.partial, "paged")
        return card_id

    def scroll_to_card(self, card_id: str) -> str | None:
        """Scroll ``card_id`` to the top in spread mode; return it or None."""
        document = self._document
        if document is None or document.card(card_id) is None:
            return None
        self._spread_pending_card = card_id
        self._spread_retry_count = 0
        self.enable_section_layout_reserve()
        try:
            self.call_after_refresh(lambda: self._apply_spread_scroll())
        except Exception:
            pass
        self._active_card = card_id
        return card_id

    def _apply_spread_scroll(self) -> None:
        card_id = self._spread_pending_card
        if card_id is None:
            return
        if card_id == (
            self._document.cards[0].card_id
            if self._document and self._document.cards
            else None
        ):
            try:
                scroll = self._scroll_container()
                if scroll is not None:
                    scroll.scroll_to(y=0, animate=False)
            except Exception:
                pass
            self._spread_pending_card = None
            self._spread_retry_count = 0
            return
        row = self.spread_body_start(card_id)
        if row is None:
            if self._spread_retry_count < 3:
                self._spread_retry_count += 1
                try:
                    self.call_after_refresh(lambda: self._apply_spread_scroll())
                except Exception:
                    pass
            else:
                self._spread_pending_card = None
            return
        try:
            scroll = self._scroll_container()
            if scroll is not None:
                scroll.scroll_to(y=row, animate=False)
        except Exception:
            pass
        self._spread_pending_card = None
        self._spread_retry_count = 0

    def show_document(
        self,
        document: MainDeckDocument,
        *,
        preferred_card: str | None,
        mode: RenderMode = RenderMode.PAGED,
    ) -> str | None:
        """Show ``document`` with ``preferred_card`` and ``mode``."""
        if mode is RenderMode.SPREAD:
            return self._show_document_spread(document)
        active = resolve_active_card(
            document.card_ids, preferred_card, partial=document.partial
        )
        self.prepare_section_document((document.subject, active, "paged"))
        render_key = (document.digest, active, document.partial, "paged")
        if render_key == self._last_render_key and self._document is not None:
            self._active_card = active
            self._render_mode = RenderMode.PAGED
            return active
        if not self._subject_seen or document.subject != self._previous_subject:
            self._previous_subject = document.subject
            self._subject_seen = True
            try:
                parent = self.parent
                if isinstance(parent, VerticalScroll):
                    parent.scroll_to(y=0, animate=False)
            except Exception:
                pass
        if active is None:
            renderable: Any = Text("")
        else:
            card = document.card(active)
            if card is None:
                renderable = Text("")
            else:
                renderable = Group(*card.renderables)
        digest = None if document.digest is None else f"{document.digest}:{active}"
        self._apply_section_content(renderable, digest, layout=True)
        self._document = document
        self._active_card = active
        self._render_mode = RenderMode.PAGED
        self._last_render_key = render_key
        return active

    def _show_document_spread(self, document: MainDeckDocument) -> str | None:
        from .separators import main_separator_for

        self.prepare_section_document((document.subject, "spread"))
        render_key = (document.digest, "spread", document.partial)
        if render_key == self._last_render_key and self._document is not None:
            self._render_mode = RenderMode.SPREAD
            pending = self._spread_pending_card
            if pending is not None and document.card(pending) is not None:
                # Explicit card navigation is in flight; the scroll position
                # has not caught up yet, so keep the requested card instead
                # of re-deriving from the stale scroll offset.
                self._active_card = pending
            else:
                active = self.spread_active_card()
                if active is not None:
                    self._active_card = active
            return self._active_card
        is_new_subject = (
            not self._subject_seen or document.subject != self._previous_subject
        )
        if is_new_subject:
            self._previous_subject = document.subject
            self._subject_seen = True
        if not document.cards:
            self._apply_section_content(Text(""), None, layout=True)
            self._document = document
            self._active_card = None
            self._render_mode = RenderMode.SPREAD
            self._last_render_key = render_key
            return None
        try:
            accent = self._spread_accent()
        except Exception:
            accent = ""
        parts: list[Any] = []
        for index, card in enumerate(document.cards):
            if index > 0:
                parts.append(
                    main_separator_for(card.card_id, card.title, accent=accent)
                )
            parts.extend(list(card.renderables))
        digest = None if document.digest is None else f"{document.digest}:spread"
        self._apply_section_content(Group(*parts), digest, layout=True)
        self._document = document
        self._render_mode = RenderMode.SPREAD
        self._last_render_key = render_key
        # Active card is scroll-derived; default to first until scroll settles.
        if is_new_subject:
            self._active_card = document.cards[0].card_id
            try:
                scroll = self._scroll_container()
                if scroll is not None:
                    scroll.scroll_to(y=0, animate=False)
            except Exception:
                pass
        else:
            pending = self._spread_pending_card
            if pending is not None and document.card(pending) is not None:
                # Same as above: explicit navigation wins over the stale
                # scroll offset until the deferred scroll is applied.
                self._active_card = pending
            else:
                derived = self.spread_active_card()
                if derived is not None:
                    self._active_card = derived
        # Honor a one-shot scroll-to-card recorded for duplicate panels.
        pending = getattr(self, "_spread_pending_card", None)
        if pending is not None and document.card(pending) is not None:
            try:
                self.call_after_refresh(lambda: self._apply_spread_scroll())
            except Exception:
                pass
        return self._active_card

    def _spread_accent(self) -> str:
        try:
            parent = self.parent
            panel = parent.parent if parent is not None else None
            resolver = getattr(panel, "_resolve_accent", None)
            if callable(resolver):
                from .model import DeckId

                return str(resolver(DeckId.MAIN))
        except Exception:
            pass
        return "#B48EAD"
