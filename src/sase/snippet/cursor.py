"""No-I/O snippet-trigger detection under a prompt cursor.

Used to seed the Snippets panel from ``gT`` / ``Ctrl+G T``. Call scanning is
syntactic; a bare trigger is returned only when it already exists in the
in-memory catalog handed in by the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
import re

_SNIPPET_CALL_RE = re.compile(
    r"#\[(?P<trigger>[A-Za-z_][A-Za-z0-9_]*)(?:\([^[\]]*\)|:[^\]]+)?\]"
)
_TRIGGER_CHAR = re.compile(r"[A-Za-z0-9_]")


def snippet_trigger_at_offset(
    text: str,
    offset: int,
    known: Mapping[str, str] | None = None,
) -> str | None:
    """Return the snippet trigger at *offset* if it can be resolved without I/O.

    Prefers a surrounding ``#[trigger]``, ``#[trigger(value)]``, or
    ``#[trigger:value]`` call. Falls back to the alphanumeric/underscore word
    at the cursor when that word is a key of *known*.
    """
    if not text:
        return None
    clamped = max(0, min(offset, len(text)))
    call = _call_trigger_at(text, clamped)
    if call is not None:
        return call
    word = _word_at(text, clamped)
    if word is None:
        return None
    if known is not None and word in known:
        return word
    return None


def _call_trigger_at(text: str, offset: int) -> str | None:
    for match in _SNIPPET_CALL_RE.finditer(text):
        if match.start() <= offset <= match.end():
            return match.group("trigger")
    return None


def _word_at(text: str, offset: int) -> str | None:
    index = offset
    if index >= len(text) or not _TRIGGER_CHAR.match(text[index] or ""):
        index = offset - 1
    if index < 0 or index >= len(text) or not _TRIGGER_CHAR.match(text[index]):
        return None
    start = index
    while start > 0 and _TRIGGER_CHAR.match(text[start - 1]):
        start -= 1
    end = index + 1
    while end < len(text) and _TRIGGER_CHAR.match(text[end]):
        end += 1
    word = text[start:end]
    if not word or not (word[0].isalpha() or word[0] == "_"):
        return None
    return word


__all__ = ["snippet_trigger_at_offset"]
