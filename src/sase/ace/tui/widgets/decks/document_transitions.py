"""Hierarchical reading anchors for card-document deck transitions.

One :class:`ReadingAnchor` captures ``(card_id, block_id, offset_rows,
pinned)`` before a spread/paged recomposition and restores the most
specific target that survives: same block + offset (clamped >= 0), then
card top, then card default, then document default. With
``block_id=None`` the restore reproduces the pre-block transition math
exactly. Every helper takes the card-document deck explicitly and reaches
its ``(view, document, deck)`` triple through the ``card_document_host``
accessor; Main-only wrappers live in ``panel_transitions.py``.

This module is a facade: the implementation lives in
:mod:`sase.ace.tui.widgets.decks.document_transitions_capture` and
:mod:`sase.ace.tui.widgets.decks.document_transitions_apply`.
"""

from __future__ import annotations

from ._document_transitions import ReadingAnchor
from .document_transitions_apply import DeckPanelDocumentApplyMixin
from .document_transitions_capture import DeckPanelDocumentCaptureMixin

__all__ = [
    "DeckPanelDocumentTransitionsMixin",
    "ReadingAnchor",
]


class DeckPanelDocumentTransitionsMixin(
    DeckPanelDocumentCaptureMixin,
    DeckPanelDocumentApplyMixin,
):
    """Deck spread/paged transitions with hierarchical reading anchors."""
