"""Pure next-word placement helpers for the prompt input chain.

Classifies the cursor into ``none`` / ``inline_eol`` / ``inline_tail`` /
``peek`` (plan ``202609/next_word_autosuggest.md`` §4.1) and fits ghost
words against the tail-shifted remainder of the cursor's wrapped row, so
widget code stays thin and unit tests never need a mounted TextArea. The
Rust core owns gating; this module only decides where a gated guess may
be shown inline. It also owns the mid-sentence peek helpers: the
redundancy trim and the styled, width-degrading border-subtitle peek
(§4.3), which never moves prose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._ranking_signal_rows import (
    SEQUENCE_COLOR,
    SEQUENCE_GLYPH,
)


class NextWordPlacement(Enum):
    """Where a next-word guess may be shown for the current cursor."""

    #: No guess: a word character follows the cursor.
    NONE = "none"
    #: The rest of the logical line is blank: ghost at end of line.
    INLINE_EOL = "inline_eol"
    #: Only a short closing tail follows: ghost before the tail.
    INLINE_TAIL = "inline_tail"
    #: Prose follows, or no ghost word fits: the border peek (next phase).
    PEEK = "peek"


#: Non-space characters allowed in a closing tail: closers, quotes, and
#: clause punctuation. Backticks are excluded because code spans block in
#: the core, so a rest containing one is never a tail. Spaces are always
#: allowed between tail characters.
NEXT_WORD_CLOSING_TAIL_CHARS = frozenset(")]}\"'”’.,;:!?…*_")

#: Maximum number of non-space characters in a closing tail.
NEXT_WORD_MAX_TAIL_CHARS = 8

#: Extra word characters beyond ``str.isalnum`` for placement: a word
#: character after the cursor means the cursor sits inside a word.
_NEXT_WORD_PLACEMENT_WORD_CHARS = frozenset({"_", "'", "’", "-"})

#: Trailing clause punctuation skipped when looking for the word token
#: before a typed trigger character.
_NEXT_WORD_TRIGGER_TRAILING_PUNCT = frozenset(",;:!?.)]}“”\"'’*…")

#: Peek hint segments: the full ``[^T] word  [^L] all`` matches
#: ``NEXT_WORD_GHOST_HINT`` in ``next_word_completion`` (kept in sync by
#: test, not by import, to avoid a placement/completion import cycle).
NEXT_WORD_PEEK_HINT_WORD = "[^T] word"
NEXT_WORD_PEEK_HINT_ALL = "[^L] all"

#: Word tokens for the peek redundancy trim: the placement word rules
#: (alphanumeric plus ``_ ' ’ -``).
_NEXT_WORD_PEEK_WORD_RE = re.compile(r"[A-Za-z0-9_'\-’]+")


@dataclass(frozen=True, slots=True)
class NextWordPeek:
    """Mid-sentence peek state: a gated guess anchored at a snapshot.

    ``words`` are the trimmed preview words, ``revealed`` tracks the
    reveal beat (explicit requests and accepts reveal immediately while
    auto peeks wait), and ``word_completion`` stays ``None`` until the
    mid-word phase composes suffix-plus-continuation peeks.
    """

    anchor_offset: int
    anchor_text: str
    words: tuple[str, ...]
    revealed: bool
    word_completion: object | None = None


def _is_placement_word_char(character: str) -> bool:
    """Return whether *character* counts as a word character for placement."""
    return character.isalnum() or character in _NEXT_WORD_PLACEMENT_WORD_CHARS


def _next_word_closing_tail(rest_of_line: str) -> str | None:
    """Return *rest_of_line* when it is a valid closing tail, else ``None``.

    A tail is non-blank, holds at most ``NEXT_WORD_MAX_TAIL_CHARS``
    non-space characters, and every non-space character is in
    ``NEXT_WORD_CLOSING_TAIL_CHARS``.
    """
    if rest_of_line.strip() == "":
        return None
    non_space = sum(1 for char in rest_of_line if not char.isspace())
    if non_space == 0 or non_space > NEXT_WORD_MAX_TAIL_CHARS:
        return None
    for char in rest_of_line:
        if char.isspace():
            continue
        if char not in NEXT_WORD_CLOSING_TAIL_CHARS:
            return None
    return rest_of_line


def next_word_rest_of_line(text: str, cursor_offset: int) -> str:
    """Return the text after the cursor on its current line."""
    line_end = text.find("\n", cursor_offset)
    if line_end == -1:
        line_end = len(text)
    return text[cursor_offset:line_end]


def classify_next_word_placement(text: str, cursor_offset: int) -> NextWordPlacement:
    """Classify the cursor for ghost placement from the document text only.

    ``none`` when a word character follows the cursor (mid-word),
    ``inline_eol`` when the rest of the logical line is blank,
    ``inline_tail`` when only a closing tail follows, and ``peek`` for
    anything else.
    """
    if cursor_offset < 0 or cursor_offset > len(text):
        return NextWordPlacement.NONE
    if cursor_offset < len(text) and _is_placement_word_char(text[cursor_offset]):
        return NextWordPlacement.NONE
    rest = next_word_rest_of_line(text, cursor_offset)
    if rest.strip() == "":
        return NextWordPlacement.INLINE_EOL
    if _next_word_closing_tail(rest) is not None:
        return NextWordPlacement.INLINE_TAIL
    return NextWordPlacement.PEEK


def next_word_is_last_wrapped_section(
    wrap_breaks: Sequence[int],
    cursor_col: int,
) -> bool:
    """Return whether *cursor_col* sits on the final wrapped section.

    *wrap_breaks* are the wrapped-document break columns for the cursor's
    logical row (the same offsets ``_next_word_available_width`` scans).
    A break past the cursor means a later section follows.
    """
    for break_col in wrap_breaks:
        if break_col > cursor_col:
            return False
    return True


def fit_next_word_ghost_with_tail(
    words: list[str],
    separator: str,
    available_width: int,
    max_words: int,
    tail: str,
) -> list[str]:
    """Truncate *words* to whole words fitting beside the shifted *tail*.

    The ghost plus the shifted tail must fit *available_width*, the
    remaining cells of the cursor's wrapped row, so the tail's cells come
    off the budget first. Caps at *max_words*, then drops trailing words.
    Returns ``[]`` when even the first word does not fit (the placement
    becomes ``peek``).
    """
    budget = available_width - (cell_len(tail) if tail else 0)
    if budget <= 0 or not words:
        return []
    capped = list(words[: max(1, max_words)])
    while capped:
        ghost = f"{separator}{' '.join(capped)}"
        if cell_len(ghost) <= budget:
            return capped
        capped.pop()
    return []


def _next_word_following_words(text_after_cursor: str) -> list[str]:
    """Return the word tokens following the cursor for the peek trim.

    Whitespace and punctuation are skipped; tokens follow the placement
    word rules so ``don't`` stays one word.
    """
    return _NEXT_WORD_PEEK_WORD_RE.findall(text_after_cursor)


def trim_next_word_peek_words(
    words: Sequence[str],
    text_after_cursor: str,
) -> list[str]:
    """Cut a peek before the first word the text already has (§4.3).

    The peek words are compared casefolded against the first word after
    the cursor. The peek is cut before the first peek word equal to that
    following word; when the very first peek word already follows, no
    peek is offered. A guess the text already contains is never shown.
    """
    trimmed = [word for word in words if word]
    if not trimmed:
        return []
    following = _next_word_following_words(text_after_cursor)
    if not following:
        return list(trimmed)
    first_following = following[0].casefold()
    for index, word in enumerate(trimmed):
        if word.casefold() == first_following:
            return list(trimmed[:index])
    return list(trimmed)


def _peek_text_style(
    variables: Mapping[str, str] | None, name: str, *, fallback: str
) -> str:
    """Return the theme style for the peek's first or preview words.

    ``$text``/``$text-muted`` resolve from the app theme variables, but a
    theme may express them as Textual ``auto`` specs that Rich cannot
    parse for a border subtitle. Values are validated with Rich: anything
    unparseable falls back (bold default reads as ``$text``, dim reads
    as ``$text-muted`` in every theme).
    """
    if variables is not None:
        try:
            value = variables.get(name)
        except Exception:
            value = None
        if value:
            candidate = str(value)
            try:
                from rich.style import Style as _RichStyle

                _RichStyle.parse(candidate)
            except Exception:
                pass
            else:
                return candidate
    return fallback


def build_next_word_peek_text(
    words: Sequence[str],
    *,
    variables: Mapping[str, str] | None = None,
    available_width: int,
) -> Text | None:
    """Build the styled violet peek for *words* within *available_width*.

    The glyph uses the sequence violet, the first word (what ``Ctrl+T``
    inserts) is bold ``$text``, preview words use ``$text-muted``, and
    the hints keep the existing subtitle style. Degradation drops
    trailing preview words first, then ``[^L] all``, then ``[^T] word``;
    a word is never cut. Returns ``None`` when even ``⇢ <first>`` does
    not fit, so the cursor readout keeps priority.
    """
    trimmed = [word for word in words if word]
    if not trimmed or available_width <= 0:
        return None
    try:
        text_style = _peek_text_style(variables, "text", fallback="bold")
        preview_style = _peek_text_style(variables, "text-muted", fallback="dim")
    except Exception:
        text_style = "bold"
        preview_style = "dim"
    first_style = text_style if text_style.startswith("bold") else f"bold {text_style}"

    def _plain(preview_count: int, *, with_word: bool, with_all: bool) -> str:
        parts = [SEQUENCE_GLYPH, " ", " ".join(trimmed[:preview_count])]
        if with_word or with_all:
            parts.append("  ")
        if with_word:
            parts.append(NEXT_WORD_PEEK_HINT_WORD)
        if with_word and with_all:
            parts.append("  ")
        if with_all:
            parts.append(NEXT_WORD_PEEK_HINT_ALL)
        return "".join(parts)

    def _build(preview_count: int, *, with_word: bool, with_all: bool) -> Text:
        result = Text(no_wrap=True)
        result.append(SEQUENCE_GLYPH, style=f"bold {SEQUENCE_COLOR}")
        result.append(" ")
        result.append(trimmed[0], style=first_style or "bold")
        for word in trimmed[1:preview_count]:
            result.append(" ")
            result.append(word, style=preview_style)
        if with_word or with_all:
            result.append("  ")
        if with_word:
            result.append(NEXT_WORD_PEEK_HINT_WORD)
        if with_word and with_all:
            result.append("  ")
        if with_all:
            result.append(NEXT_WORD_PEEK_HINT_ALL)
        return result

    for count in range(len(trimmed), 0, -1):
        if cell_len(_plain(count, with_word=True, with_all=True)) <= available_width:
            return _build(count, with_word=True, with_all=True)
    if cell_len(_plain(1, with_word=True, with_all=False)) <= available_width:
        return _build(1, with_word=True, with_all=False)
    if cell_len(_plain(1, with_word=False, with_all=False)) <= available_width:
        return _build(1, with_word=False, with_all=False)
    return None


def next_word_auto_space_eligible(text: str, cursor_offset: int) -> bool:
    """Return whether a just-typed character may trigger an ``auto`` ghost.

    The typed character (just before the cursor) must be a non-word
    character following a word token: trailing clause punctuation between
    the word and the trigger is skipped, so ``", "`` is eligible while a
    doubled space or a line start has no word token. Mid-line triggers are
    eligible when the placement is not ``none``; inline placements render
    while a ``peek`` placement renders nothing until the peek phase.
    """
    if cursor_offset <= 0 or cursor_offset > len(text):
        return False
    if _is_placement_word_char(text[cursor_offset - 1]):
        return False
    if classify_next_word_placement(text, cursor_offset) is NextWordPlacement.NONE:
        return False
    index = cursor_offset - 2
    while index >= 0 and text[index] in _NEXT_WORD_TRIGGER_TRAILING_PUNCT:
        index -= 1
    if index < 0:
        return False
    return _is_placement_word_char(text[index])


__all__ = [
    "NEXT_WORD_CLOSING_TAIL_CHARS",
    "NEXT_WORD_MAX_TAIL_CHARS",
    "NEXT_WORD_PEEK_HINT_ALL",
    "NEXT_WORD_PEEK_HINT_WORD",
    "NextWordPeek",
    "NextWordPlacement",
    "build_next_word_peek_text",
    "classify_next_word_placement",
    "fit_next_word_ghost_with_tail",
    "next_word_auto_space_eligible",
    "next_word_is_last_wrapped_section",
    "next_word_rest_of_line",
    "trim_next_word_peek_words",
]
