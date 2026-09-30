"""Pure next-word ghost helpers for the prompt input chain.

All width, separator, and ghost-text decisions live here so widget code stays
thin and unit tests never need a mounted TextArea. The Rust core owns gating;
this module only formats a gated ``ghost: [word]`` list for display.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len

#: Border hint shown while a next-word ghost is visible.
NEXT_WORD_GHOST_HINT = "[^T] word  [^F] all"

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


def fit_next_word_ghost(
    words: list[str],
    separator: str,
    available_width: int,
    max_words: int,
) -> list[str]:
    """Truncate *words* to whole words that fit in *available_width*.

    Caps at *max_words* first, then drops trailing words until the joined
    ghost fits. Returns ``[]`` when even the first word does not fit.
    """
    if available_width <= 0 or not words:
        return []
    capped = list(words[: max(1, max_words)])
    while capped:
        ghost = build_next_word_ghost_text(capped, separator)
        if cell_len(ghost) <= available_width:
            return capped
        capped.pop()
    return []


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
    that ``self.suggestion`` equals this remainder and that the cursor row
    is unchanged with a blank rest-of-line.
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


#: Trailing clause punctuation allowed between a word and an auto-mode space.
_NEXT_WORD_AUTO_TRAILING_PUNCT = frozenset(",;:!?.)]}“”\"'’*…")

#: Word-ish characters for the auto-mode word-token check (mirrors
#: ``is_word_character`` in ``prompt_word_completion`` plus apostrophes).
_NEXT_WORD_AUTO_WORD_CHARS = frozenset({"-", "_", "'", "’"})


def next_word_auto_space_eligible(text: str, cursor_offset: int) -> bool:
    """Return whether a just-typed space may trigger an ``auto`` ghost.

    The cursor must sit just after the inserted space at end of line, and
    the space must follow a word token (trailing clause punctuation such
    as ``,`` is skipped, so ``", "`` is eligible while ``". "`` is left to
    the model gate, which never predicts from a ``<s>``-only context).
    """
    if cursor_offset <= 0 or cursor_offset > len(text):
        return False
    if text[cursor_offset - 1] != " ":
        return False
    if next_word_rest_of_line(text, cursor_offset).strip() != "":
        return False
    index = cursor_offset - 2
    while index >= 0 and text[index] in _NEXT_WORD_AUTO_TRAILING_PUNCT:
        index -= 1
    if index < 0:
        return False
    char = text[index]
    return char.isalnum() or char in _NEXT_WORD_AUTO_WORD_CHARS


def next_word_rest_of_line(text: str, cursor_offset: int) -> str:
    """Return the text after the cursor on its current line."""
    line_end = text.find("\n", cursor_offset)
    if line_end == -1:
        line_end = len(text)
    return text[cursor_offset:line_end]


def next_word_has_word_suffix(text: str, cursor_offset: int) -> bool:
    """Return whether an identifier-like character follows the cursor."""
    return cursor_offset < len(text) and text[cursor_offset] in _NEXT_WORD_SUFFIX_CHARS


__all__ = [
    "NEXT_WORD_GHOST_HINT",
    "NEXT_WORD_NO_GUESS_HINT",
    "NEXT_WORD_NO_GUESS_RECENT_FILES_HINT",
    "NEXT_WORD_WARMING_HINT",
    "NextWordChain",
    "NextWordGhost",
    "build_next_word_ghost_text",
    "fit_next_word_ghost",
    "next_word_auto_space_eligible",
    "next_word_chain_armed",
    "next_word_ghost_expected",
    "next_word_has_word_suffix",
    "next_word_leading_separator",
    "next_word_rest_of_line",
    "split_next_word_one",
]
