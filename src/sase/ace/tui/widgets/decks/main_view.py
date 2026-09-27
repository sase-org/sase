"""Main deck card view inside a deck panel scroll.

Thin ``DeckId.MAIN`` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView`.
"""

from __future__ import annotations

from typing import Any

from .document_view import CardDocumentView
from .model import DeckId


class MainDeckView(CardDocumentView):
    """One Main card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Main deck view."""
        super().__init__(DeckId.MAIN, **kwargs)


__all__ = ["MainDeckView"]
