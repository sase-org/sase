"""Bounded view-state trail for the link-traversing pager."""

from __future__ import annotations

from collections.abc import MutableSequence
from dataclasses import dataclass

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
)
from sase.ace.tui.widgets.vim_search_controller import VimSearchMode
from sase.pager._labels import LabelWindowScope
from sase.pager.document import PagerDocument

PAGER_TRAIL_LIMIT = 32


@dataclass(frozen=True, slots=True)
class PagerSearchState:
    """A restorable snapshot of ``VimSearchController`` state."""

    mode: VimSearchMode
    direction: SearchDirection
    query: str
    corpus: str
    line_starts: tuple[int, ...]
    match_spans: tuple[SearchSpan, ...]
    current_selection: SearchSelection | None
    origin_offset: int
    restore_scroll_x: int
    restore_scroll_y: int
    last_search: tuple[str, SearchDirection] | None


@dataclass(frozen=True, slots=True)
class PagerTrailEntry:
    """One complete pager view that back/forward travel can restore."""

    document: PagerDocument
    document_identity: str
    document_title: str
    section_identity: str
    section_title: str
    section_kind: str
    scroll_x: int
    scroll_y: int
    search: PagerSearchState
    label_anchor: LabelWindowScope | None


def append_bounded_trail(
    entries: MutableSequence[PagerTrailEntry],
    entry: PagerTrailEntry,
    *,
    limit: int = PAGER_TRAIL_LIMIT,
) -> None:
    """Append ``entry`` and drop oldest crumbs beyond ``limit``."""
    entries.append(entry)
    overflow = len(entries) - limit
    if overflow > 0:
        del entries[:overflow]


__all__ = [
    "PAGER_TRAIL_LIMIT",
    "PagerSearchState",
    "PagerTrailEntry",
    "append_bounded_trail",
]
