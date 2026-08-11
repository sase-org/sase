"""Vim-style prompt search helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

SearchDirection = Literal["forward", "reverse"]
SearchSpan = tuple[int, int]


@dataclass(frozen=True)
class SearchSelection:
    """Selected match index plus whether selection wrapped around the buffer."""

    index: int
    wrapped: bool


@dataclass(frozen=True)
class PromptSearchQuery:
    """A shared prompt-stack search register entry: query plus match semantics.

    Carrying ``whole_word`` / ``smartcase`` alongside the query and direction
    keeps ``n`` / ``N`` reusing the exact match rules a ``*`` / ``#`` / ``/`` /
    ``?`` search recorded, instead of re-deriving a plain smartcase substring
    search from the bare string.
    """

    query: str
    direction: SearchDirection
    whole_word: bool = False
    smartcase: bool = True


def _is_smartcase_case_sensitive(query: str) -> bool:
    """Return whether Vim smartcase should treat *query* as case-sensitive."""
    return any(char.isupper() for char in query)


def _is_keyword_char(ch: str) -> bool:
    """Return whether *ch* is a vim keyword character (mirrors ``_char_class``)."""
    return ch.isalnum() or ch == "_"


def find_search_matches(
    text: str,
    query: str,
    *,
    smartcase: bool = True,
    whole_word: bool = False,
) -> tuple[SearchSpan, ...]:
    """Return ordered literal search spans for *query* in *text*.

    Matching is case-insensitive unless smartcase is disabled or *query*
    contains an uppercase character. Overlapping matches are included. When
    *whole_word* is set, a ``\\b`` boundary is required on each edge of *query*
    that starts/ends on a keyword character (vim ``\\<`` / ``\\>``); an edge
    bordered by punctuation is left unconstrained so the query still matches.
    """
    if not query:
        return ()

    flags = 0
    if smartcase and not _is_smartcase_case_sensitive(query):
        flags = re.IGNORECASE

    escaped = re.escape(query)
    if whole_word:
        prefix = r"\b" if _is_keyword_char(query[0]) else ""
        suffix = r"\b" if _is_keyword_char(query[-1]) else ""
        escaped = f"{prefix}{escaped}{suffix}"

    pattern = re.compile(f"(?=({escaped}))", flags)
    return tuple((match.start(1), match.end(1)) for match in pattern.finditer(text))


def select_search_match(
    matches: tuple[SearchSpan, ...],
    origin: int,
    direction: SearchDirection,
    *,
    include_origin: bool = True,
) -> SearchSelection | None:
    """Select the nearest match from *origin* in *direction*.

    When no match exists in the requested direction, selection wraps to the
    first/last match and reports ``wrapped=True``.
    """
    if not matches:
        return None

    origin = max(0, origin)
    if direction == "forward":
        for index, (start, _end) in enumerate(matches):
            if start > origin or (include_origin and start == origin):
                return SearchSelection(index=index, wrapped=False)
        return SearchSelection(index=0, wrapped=True)
    if direction == "reverse":
        for index in range(len(matches) - 1, -1, -1):
            start, _end = matches[index]
            if start < origin or (include_origin and start == origin):
                return SearchSelection(index=index, wrapped=False)
        return SearchSelection(index=len(matches) - 1, wrapped=True)

    msg = f"unknown search direction: {direction!r}"
    raise ValueError(msg)
