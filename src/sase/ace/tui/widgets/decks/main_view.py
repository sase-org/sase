"""Main deck card view inside a deck panel scroll."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..prompt_panel._section_view import SectionViewMixin
from .main_document import MainDeckDocument
from .model import resolve_active_card


class MainDeckView(SectionViewMixin, Static):
    """One Main card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Main deck view."""
        super().__init__(**kwargs)
        self._document: MainDeckDocument | None = None
        self._active_card: str | None = None
        self._last_render_key: tuple[object, object, object] | None = None
        self._previous_subject: object | None = None
        self._subject_seen: bool = False

    @property
    def active_card_id(self) -> str | None:
        """Return the active card id."""
        return self._active_card

    def show_card(self, card_id: str) -> str | None:
        """Activate ``card_id`` from the stored document; return it or None."""
        document = self._document
        if document is None:
            return None
        card = document.card(card_id)
        if card is None:
            return None
        self.prepare_section_document((document.subject, card_id))
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
        self._last_render_key = (document.digest, card_id, document.partial)
        return card_id

    def show_document(
        self, document: MainDeckDocument, *, preferred_card: str | None
    ) -> str | None:
        """Show ``document`` with ``preferred_card``; return the active card."""
        active = resolve_active_card(
            document.card_ids, preferred_card, partial=document.partial
        )
        self.prepare_section_document((document.subject, active))
        render_key = (document.digest, active, document.partial)
        if render_key == self._last_render_key and self._document is not None:
            self._active_card = active
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
        self._last_render_key = render_key
        return active
