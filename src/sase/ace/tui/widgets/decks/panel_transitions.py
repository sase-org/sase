"""Hierarchical reading anchors for deck and block mode transitions.

Main-only wrappers over
:class:`~sase.ace.tui.widgets.decks.document_transitions.DeckPanelDocumentTransitionsMixin`,
which holds the deck-parameterized implementation.
"""

from __future__ import annotations

from typing import Any

from .document_transitions import (
    DeckPanelDocumentTransitionsMixin,
    ReadingAnchor,
)
from .model import DeckId, RenderMode

__all__ = [
    "DeckPanelTransitionsMixin",
]


class DeckPanelTransitionsMixin(DeckPanelDocumentTransitionsMixin):
    """Deck spread/paged transitions with hierarchical reading anchors."""

    _panel_index: int
    _main_active_card: str | None

    def _capture_reading_anchor(
        self, document: Any, *, old_mode: RenderMode
    ) -> ReadingAnchor:
        return self._capture_document_reading_anchor(
            DeckId.MAIN, document, old_mode=old_mode
        )

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
        self._refresh_document_mode_for_shown(DeckId.MAIN)

    def _restore_block_transition(
        self, anchor: ReadingAnchor, active: str | None
    ) -> None:
        """Restore a block-anchored position after a mode recomposition."""
        self._restore_document_block_transition(DeckId.MAIN, anchor, active)

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
        return self._apply_document_transition(
            DeckId.MAIN,
            document,
            preferred_card,
            old_mode=old_mode,
            new_mode=new_mode,
            is_new_subject=is_new_subject,
            previous_document=previous_document,
        )
