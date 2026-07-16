"""Pure helpers for generic insert-mode auto-pairing in the prompt input.

These planners give the Textual ``PromptTextArea`` a small, fixed-rule
auto-pair feature for bracket pairs (``()``, ``[]``, ``{}``) and
same-character quotes (``'``, ``"``, and `````). They plan in-memory text edits
only and never
touch the event loop (no I/O, bounded string scanning over the current document
text). Mirrors the conservative subset of ``windwp/nvim-autopairs`` we want:
auto-close on a safe opener, paired-delete an empty pair, and move over an
existing closer instead of duplicating it.

Every planner takes the *current* document ``text`` plus an absolute cursor
``offset`` and returns a :class:`TextEdit` describing the replacement to apply,
or ``None`` when the edit does not apply. Callers translate the offsets back to
``(row, col)`` document locations before mutating the widget. Pair insertion and
deletion assume a collapsed selection; the caller is responsible for skipping
these planners while a selection is active.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bracket openers and their matching closers.
_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _OPEN_TO_CLOSE.items()}
# Bracket closers, i.e. characters that may already belong to an open pair.
_CLOSE_CHARS = frozenset(_OPEN_TO_CLOSE.values())
# Same-character delimiters that open and close themselves.
_QUOTE_CHARS = frozenset("'\"`")


@dataclass(frozen=True, slots=True)
class TextEdit:
    """A planned text edit: replace ``[start, end)`` with ``text``.

    ``cursor`` is the absolute offset the cursor should occupy after the edit.
    """

    start: int
    end: int
    text: str
    cursor: int


def _is_word_char(char: str) -> bool:
    """Return True when *char* continues an identifier-like token."""
    return char.isalnum() or char == "_"


def _is_escaped(text: str, offset: int) -> bool:
    """Return True when the character at *offset* is backslash-escaped.

    Counts the run of consecutive ``\\`` immediately before *offset*; an odd
    run means the next character is escaped.
    """
    backslashes = 0
    index = offset - 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _next_char_allows_pair(text: str, offset: int) -> bool:
    """Return True when auto-closing at *offset* will not run into a token.

    A pair is safe to insert at end of text, before whitespace, or directly
    before an existing bracket closer. Any other following character (a word
    character, ``.``, ``$``, ``%``, another opener, a quote, ...) is treated as
    token continuation and rejects the pair.
    """
    if offset >= len(text):
        return True
    following = text[offset]
    return following.isspace() or following in _CLOSE_CHARS


def _is_matching_pair(left: str, right: str) -> bool:
    """Return True when ``left``/``right`` form a supported empty pair."""
    if left in _OPEN_TO_CLOSE:
        return _OPEN_TO_CLOSE[left] == right
    if left in _QUOTE_CHARS:
        return left == right
    return False


def _has_unmatched_opener(text: str, offset: int, opener: str, closer: str) -> bool:
    """Return True when an unmatched *opener* precedes *offset*.

    Scans ``text[:offset]`` tracking only this pair's nesting depth, so a closer
    typed before its own opener is treated as a fresh literal rather than a
    move-over.
    """
    depth = 0
    for char in text[:offset]:
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
    return depth > 0


def _count_unescaped(text: str, offset: int, char: str) -> int:
    """Count unescaped occurrences of *char* in ``text[:offset]``."""
    count = 0
    for index in range(offset):
        if text[index] == char and not _is_escaped(text, index):
            count += 1
    return count


def plan_pair_insert(text: str, offset: int, char: str) -> TextEdit | None:
    """Plan inserting a matching closer when *char* opens a supported pair.

    Bracket openers pair whenever the following character is safe (end of text,
    whitespace, or an existing closer). Quote/backtick openers are more
    conservative: the delimiter must be unescaped, the previous character must
    not be a word character or the same delimiter, and the following character
    must be safe. The planned cursor lands between the inserted delimiters.
    Returns ``None`` when no pair should be inserted.
    """
    if char in _OPEN_TO_CLOSE:
        if not _next_char_allows_pair(text, offset):
            return None
        closer = _OPEN_TO_CLOSE[char]
        return TextEdit(start=offset, end=offset, text=char + closer, cursor=offset + 1)
    if char in _QUOTE_CHARS:
        if _is_escaped(text, offset):
            return None
        previous = text[offset - 1] if offset > 0 else ""
        # A repeated delimiter (``` `` ``` after the first auto-pair) must stay
        # literal so Markdown fences / code spans remain typeable.
        if previous == char:
            return None
        if previous and _is_word_char(previous):
            return None
        if not _next_char_allows_pair(text, offset):
            return None
        return TextEdit(start=offset, end=offset, text=char + char, cursor=offset + 1)
    return None


def plan_pair_close_skip(text: str, offset: int, char: str) -> TextEdit | None:
    """Plan moving over an existing closer instead of inserting a duplicate.

    Applies only when *char* is exactly the next character and context shows the
    closer belongs to a live pair: brackets require an unmatched opener of the
    same kind before the cursor, and quotes require an odd count of unescaped
    matching delimiters before the cursor. The edit inserts nothing and advances
    the cursor one character. Returns ``None`` otherwise.
    """
    if offset >= len(text) or text[offset] != char:
        return None
    if char in _CLOSE_TO_OPEN:
        opener = _CLOSE_TO_OPEN[char]
        if not _has_unmatched_opener(text, offset, opener, char):
            return None
        return TextEdit(start=offset, end=offset, text="", cursor=offset + 1)
    if char in _QUOTE_CHARS:
        if _count_unescaped(text, offset, char) % 2 == 0:
            return None
        return TextEdit(start=offset, end=offset, text="", cursor=offset + 1)
    return None


def plan_pair_delete_left(text: str, offset: int) -> TextEdit | None:
    """Plan deleting both sides when backspacing the opener of an empty pair.

    Applies only when the cursor sits between an opener and its matching closer
    (``(|)``, ``[|]``, ``{|}``, ``'|'``, ...). Non-empty pairs return ``None`` so
    the caller falls back to a single-character delete.
    """
    if offset < 1 or offset >= len(text):
        return None
    if _is_matching_pair(text[offset - 1], text[offset]):
        return TextEdit(start=offset - 1, end=offset + 1, text="", cursor=offset - 1)
    return None


def plan_pair_delete_right(text: str, offset: int) -> TextEdit | None:
    """Plan deleting both sides when forward-deleting the opener of an empty pair.

    Applies only when the cursor sits directly before an empty pair (``|()``,
    ``|''``, ...). Non-empty pairs return ``None`` so the caller falls back to a
    single-character delete.
    """
    if offset < 0 or offset + 1 >= len(text):
        return None
    if _is_matching_pair(text[offset], text[offset + 1]):
        return TextEdit(start=offset, end=offset + 2, text="", cursor=offset)
    return None
