"""Bounded, cross-document caches for prepared pager syntax results.

Kept free of Textual and I/O so the eviction/bounding rules are unit
testable without booting an App. A screen owns one of each cache for its
lifetime; callers compute :func:`content_digest` off the event loop (inside
the worker that already reads the full section text to lex it) so an open
or scroll never hashes a whole document synchronously.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib

from rich.text import Text

from sase.pager.syntax import SyntaxResult

#: Cross-document reuse cap (design doc: "bound cross-document reuse to 24
#: sections"). Not a per-document limit -- see ``MAX_DOCUMENT_SYNTAX_SPANS``
#: in ``_screen_syntax.py`` for the separate current-document span budget.
MAX_CACHED_SECTIONS = 24
MAX_CACHED_SPANS = 200_000


def content_digest(source: str) -> str:
    """Return a stable content-identity digest for *source*."""
    return hashlib.blake2b(source.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True, slots=True)
class ResultCacheKey:
    """Cache key for a lexed :class:`SyntaxResult` (spans, no color)."""

    digest: str
    language: str


@dataclass(frozen=True, slots=True)
class StyledCacheKey:
    """Cache key for a theme-styled ``Text`` base.

    Two sections can share ``digest``/``language`` but differ in whether
    their original body already carried producer style (see
    ``text_has_producer_style``), which changes ``highlight_source``'s
    disposition, so it is folded into this key alongside the theme
    signature.
    """

    digest: str
    language: str
    theme_signature: str
    producer_eligible: bool


class SyntaxResultCache:
    """LRU cache of lexed results, bounded by section count and span total."""

    def __init__(
        self,
        *,
        max_sections: int = MAX_CACHED_SECTIONS,
        max_spans: int = MAX_CACHED_SPANS,
    ) -> None:
        self._max_sections = max_sections
        self._max_spans = max_spans
        self._entries: OrderedDict[ResultCacheKey, SyntaxResult] = OrderedDict()
        self._total_spans = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def total_spans(self) -> int:
        return self._total_spans

    def get(self, key: ResultCacheKey) -> SyntaxResult | None:
        result = self._entries.get(key)
        if result is not None:
            self._entries.move_to_end(key)
        return result

    def put(self, key: ResultCacheKey, result: SyntaxResult) -> None:
        if key in self._entries:
            self._total_spans -= len(self._entries[key].spans)
        self._entries[key] = result
        self._entries.move_to_end(key)
        self._total_spans += len(result.spans)
        self._evict()

    def _evict(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_sections
            or self._total_spans > self._max_spans
        ):
            evicted = self._entries.popitem(last=False)[1]
            self._total_spans -= len(evicted.spans)


class StyledTextCache:
    """LRU cache of styled ``Text`` bases, bounded to the current theme.

    Callers ``clear()`` this on a theme change instead of letting old-theme
    entries linger under LRU pressure (design doc: "bound displayed Text
    variants to the current palette rather than retaining every previous
    theme").
    """

    def __init__(self, *, max_sections: int = MAX_CACHED_SECTIONS) -> None:
        self._max_sections = max_sections
        self._entries: OrderedDict[StyledCacheKey, Text] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: StyledCacheKey) -> Text | None:
        text = self._entries.get(key)
        if text is not None:
            self._entries.move_to_end(key)
        return text

    def put(self, key: StyledCacheKey, text: Text) -> None:
        self._entries[key] = text
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_sections:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


__all__ = [
    "MAX_CACHED_SECTIONS",
    "MAX_CACHED_SPANS",
    "ResultCacheKey",
    "StyledCacheKey",
    "StyledTextCache",
    "SyntaxResultCache",
    "content_digest",
]
