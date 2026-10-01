"""Pure next-word ghost helpers for the prompt input chain.

All width, separator, and ghost-text decisions live here so widget code stays
thin and unit tests never need a mounted TextArea. The Rust core owns gating;
this module only formats a gated ``ghost: [word]`` list for display.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len

from sase.ace.tui.widgets.next_word_placement import (
    next_word_auto_space_eligible,
    next_word_rest_of_line,
)

#: Border hint shown while a next-word ghost is visible.
NEXT_WORD_GHOST_HINT = "[^T] word  [^L] all"

#: Transient hint when the chain is armed but no guess is available.
NEXT_WORD_NO_GUESS_HINT = "no next-word guess"

#: Transient hint when a whitespace-boundary ``Ctrl+T`` finds no guess. It
#: teaches the moved recent-files menu, which now lives on ``Ctrl+G r``.
NEXT_WORD_NO_GUESS_RECENT_FILES_HINT = "no next-word guess  [^G r] recent files"

#: Transient hint while the prediction model is still warming.
NEXT_WORD_WARMING_HINT = "warming next words…"

#: Characters after which a leading ghost space is omitted.
_NEXT_WORD_NO_SEPARATOR_BEFORE = set(" \t\n([{'\"“‘`")

#: Identifier-like characters that force a separating space on menu accepts.
_NEXT_WORD_SUFFIX_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


@dataclass(frozen=True, slots=True)
class NextWordChain:
    """Armed chain state: the document snapshot at the last word commit."""

    anchor_offset: int
    anchor_text: str
    #: Whether the chain was armed by a mid-word trigger and expects a
    #: ``complete_current_word`` result (suffix-plus-continuation
    #: composition with old-core silence). Boundary arms leave this False.
    midword: bool = False


@dataclass(frozen=True, slots=True)
class NextWordGhost:
    """Visible ghost state: the full suggestion anchored at a commit."""

    anchor_offset: int
    full_text: str


def next_word_leading_separator(text_before_cursor: str) -> str:
    """Return the single-space separator before a ghost, or ``""``.

    The separator is omitted at the start of the text, after whitespace, or
    after an opening bracket or quote.
    """
    if not text_before_cursor:
        return ""
    if text_before_cursor[-1] in _NEXT_WORD_NO_SEPARATOR_BEFORE:
        return ""
    return " "


def build_next_word_ghost_text(words: list[str], separator: str) -> str:
    """Return the inline ghost string for *words* with *separator*."""
    if not words:
        return ""
    return f"{separator}{' '.join(words)}"


def split_next_word_one(ghost_text: str) -> str:
    """Return the first ghost word plus its leading separator.

    ``" it now"`` takes ``" it"``; a separator-only ghost takes ``""``.
    """
    if not ghost_text:
        return ""
    leading = " " if ghost_text.startswith(" ") else ""
    stripped = ghost_text.strip()
    if not stripped:
        return ""
    first = stripped.split(" ", 1)[0]
    return f"{leading}{first}"


def next_word_chain_armed(
    chain: NextWordChain | None,
    *,
    text: str,
    cursor_offset: int,
) -> bool:
    """Return whether *chain* still matches the current document."""
    if chain is None:
        return False
    return chain.anchor_offset == cursor_offset and chain.anchor_text == text


def next_word_ghost_expected(
    ghost: NextWordGhost | None,
    *,
    text: str,
    cursor_offset: int,
) -> str | None:
    """Return the remaining ghost suffix, or ``None`` when invalid.

    Valid while the text between the anchor and the cursor equals the
    consumed prefix of the full ghost text. The caller additionally checks
    that ``self.suggestion`` equals this remainder, that the cursor row is
    unchanged, and that the placement is still inline.
    """
    if ghost is None:
        return None
    if cursor_offset < ghost.anchor_offset:
        return None
    if ghost.anchor_offset > len(text) or cursor_offset > len(text):
        return None
    if cursor_offset > ghost.anchor_offset + len(ghost.full_text):
        return None
    consumed_len = cursor_offset - ghost.anchor_offset
    consumed = ghost.full_text[:consumed_len]
    if text[ghost.anchor_offset : cursor_offset] != consumed:
        return None
    return ghost.full_text[consumed_len:]


def next_word_has_word_suffix(text: str, cursor_offset: int) -> bool:
    """Return whether an identifier-like character follows the cursor."""
    return cursor_offset < len(text) and text[cursor_offset] in _NEXT_WORD_SUFFIX_CHARS


def build_midword_ghost_text(
    suffix: str,
    continuation: Sequence[str],
) -> str:
    """Return the inline ghost for a mid-word completion.

    The ghost is the core's casing-preserving *suffix* plus, when a gated
    continuation follows the completed word, a space and the continuation
    words (``"ment it now"``). An empty suffix means the typed word is
    already complete, so the ghost starts with that space
    (``" it now"``). Returns ``""`` when there is nothing to show: an
    exact word with no continuation never offers a guess.
    """
    words = [word for word in continuation if word]
    if not suffix:
        return f" {' '.join(words)}" if words else ""
    if not words:
        return suffix
    return f"{suffix} {' '.join(words)}"


def fit_midword_ghost_with_tail(
    suffix: str,
    continuation: Sequence[str],
    available_width: int,
    max_words: int,
    tail: str,
) -> str:
    """Fit a mid-word ghost beside the shifted *tail*; return ``""`` on failure.

    The ghost plus the shifted tail must fit *available_width*, the
    remaining cells of the cursor's wrapped row, so the tail's cells come
    off the budget first. The continuation caps at ``max_words - 1``
    words because ``max_words`` counts the completed word, then trailing
    continuation words drop until the composed ghost fits. Returns ``""``
    when even the suffix alone does not fit (the placement becomes
    ``peek``) or when there is nothing to show.
    """
    budget = available_width - (cell_len(tail) if tail else 0)
    if budget <= 0:
        return ""
    kept = [word for word in continuation if word][: max(0, max_words - 1)]
    while True:
        text = build_midword_ghost_text(suffix, kept)
        if not text:
            return ""
        if cell_len(text) <= budget:
            return text
        if not kept:
            return ""
        kept.pop()


def midword_peek_words(
    word: str,
    continuation: Sequence[str],
    max_words: int,
) -> list[str]:
    """Return the peek words for a mid-word completion.

    The first word is the completed *word* (what ``Ctrl+T`` finishes),
    followed by the continuation preview, capped at *max_words*.
    """
    words = [word, *[item for item in continuation if item]]
    return [item for item in words if item][: max(1, max_words)]


__all__ = [
    "NEXT_WORD_GHOST_HINT",
    "NEXT_WORD_NO_GUESS_HINT",
    "NEXT_WORD_NO_GUESS_RECENT_FILES_HINT",
    "NEXT_WORD_WARMING_HINT",
    "NextWordChain",
    "NextWordGhost",
    "build_midword_ghost_text",
    "build_next_word_ghost_text",
    "fit_midword_ghost_with_tail",
    "midword_peek_words",
    "next_word_auto_space_eligible",
    "next_word_chain_armed",
    "next_word_ghost_expected",
    "next_word_has_word_suffix",
    "next_word_leading_separator",
    "next_word_rest_of_line",
    "split_next_word_one",
]
