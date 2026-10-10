"""Shared helpers for the card-document deck-transition split.

This is the already-private (``_``-prefixed) module that owns names
needed by more than one of the new transition modules. Every helper
here carries a public (non-``_``) name so the new modules can import it
without importing a ``_``-prefixed name across files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import DeckId

__all__ = [
    "ReadingAnchor",
    "document_view",
]


@dataclass(frozen=True, slots=True)
class ReadingAnchor:
    """Hierarchical reading position across deck/block transitions."""

    card_id: str | None
    block_id: str | None
    offset_rows: int
    pinned: bool


def document_view(panel: Any, deck: DeckId) -> Any | None:
    """Return ``deck``'s card-document view on *panel*, or ``None``."""

    try:
        host = panel.card_document_host(deck)
        if host is not None:
            return host[0]
    except Exception:
        pass
    return None
