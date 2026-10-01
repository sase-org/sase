"""Host-neutral ghost-text display layer for next-word autosuggest.

Public facade: the implementation lives in ``_next_word_ghost_state``
(ghost state, gating, fitting, and reveal scheduling) and
``_next_word_ghost_peek`` (peek display, validation, auto trigger, and
accepts). This module re-exports the names that callers and tests
historically import from ``_next_word_ghost_display``.
"""

from __future__ import annotations

from ._next_word_ghost_peek import NextWordGhostPeekMixin
from ._next_word_ghost_state import (
    NEXT_WORD_GHOST_LIMIT,
    NEXT_WORD_REVEAL_DELAY_MS,
)


class NextWordGhostDisplayMixin(NextWordGhostPeekMixin):
    """Host-neutral next-word ghost state, fitting, accepts, and timing."""


__all__ = [
    "NEXT_WORD_GHOST_LIMIT",
    "NEXT_WORD_REVEAL_DELAY_MS",
    "NextWordGhostDisplayMixin",
]
