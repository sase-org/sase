"""Pure scroll-anchor helpers for the file panel (no Textual imports).

The file panel renders a numbered-gutter ``Syntax`` body for diffs and static
files. A raw row offset is not a stable position: a live diff is refetched
periodically and a newly touched file can insert a whole block above the row
the reader is looking at, sliding the text out from under them. A scroll
anchor instead pins the reader to the rendered *content* at a row — captured
as the normalized text of the nearest line start plus a wrap sub-offset — so
it can be relocated in newly rendered content even after lines shift.

Kept free of Textual imports (per the Rust-core boundary note in the plan)
so it stays trivially unit-testable and portable if this logic ever needs to
move.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import blake2b

# Matches a Rich ``Syntax(line_numbers=True)`` gutter: right-justified
# whitespace padding, the optional line-number digits, and the single
# separator space. Wrapped continuation rows render an all-blank gutter of
# the same total width, so this expression normalizes both shapes to the
# same content start column.
GUTTER_RE = re.compile(r"^\s*\d*\s?")


def _normalize_row(text: str) -> str:
    """Return *text* with its gutter prefix and trailing whitespace stripped."""
    match = GUTTER_RE.match(text)
    stripped = text[match.end() :] if match else text
    return stripped.rstrip()


def _is_line_start(text: str) -> bool:
    """Return whether *text*'s gutter carries a line number (not blank)."""
    match = GUTTER_RE.match(text)
    return match is not None and any(ch.isdigit() for ch in match.group())


def _text_at(row_texts: Sequence[str], window_start: int, row: int) -> str | None:
    """Return the rendered text for *row*, or None outside the window."""
    index = row - window_start
    if 0 <= index < len(row_texts):
        return row_texts[index]
    return None


def content_digest(content: str | None) -> str | None:
    """Return a cheap content fingerprint, or None for no content."""
    if content is None:
        return None
    return blake2b(
        content.encode("utf-8", errors="replace"), digest_size=16
    ).hexdigest()


@dataclass(frozen=True)
class _ScrollAnchor:
    """A reader's remembered position, anchored to rendered content.

    Attributes:
        row: The row offset as last observed.
        line_start_row_text: Normalized text of the nearest row at or above
            ``row`` that begins a source line (non-blank gutter), or the
            normalized text of ``row`` itself when no gutter is present.
        sub_offset: ``row`` minus the row of that line start, so a reader
            parked on a wrapped continuation row lands back on the same
            continuation row after relocation.
        content_digest: Digest of the body content this anchor was captured
            from, used to take an exact fast path when content is unchanged.
    """

    row: int
    line_start_row_text: str | None
    sub_offset: int
    content_digest: str | None


def capture_anchor(
    row: int,
    row_texts: Sequence[str],
    window_start: int,
    *,
    gutter_present: bool,
    content_digest: str | None,
) -> _ScrollAnchor:
    """Capture an anchor for *row* from the currently rendered content.

    ``row_texts[i]`` must hold the rendered text for absolute row
    ``window_start + i``; the caller supplies the bounded window it fetched
    via ``Widget.render_line``.
    """
    if row < window_start:
        return _ScrollAnchor(
            row=row,
            line_start_row_text=None,
            sub_offset=0,
            content_digest=content_digest,
        )

    if not gutter_present:
        text = _text_at(row_texts, window_start, row)
        return _ScrollAnchor(
            row=row,
            line_start_row_text=_normalize_row(text) if text is not None else None,
            sub_offset=0,
            content_digest=content_digest,
        )

    cursor = row
    while cursor > window_start:
        text = _text_at(row_texts, window_start, cursor)
        if text is not None and _is_line_start(text):
            break
        cursor -= 1
    text = _text_at(row_texts, window_start, cursor)
    return _ScrollAnchor(
        row=row,
        line_start_row_text=_normalize_row(text) if text is not None else None,
        sub_offset=row - cursor,
        content_digest=content_digest,
    )


def resolve_anchor(
    anchor: _ScrollAnchor,
    row_texts: Sequence[str],
    window_start: int,
    *,
    gutter_present: bool,
    content_digest: str | None,
    search_window: int = 512,
) -> int:
    """Return the row *anchor* now maps to in the newly rendered content.

    Takes an exact fast path when ``content_digest`` matches the digest the
    anchor was captured from. Otherwise scans outward from ``anchor.row`` in
    nearest-first order, bounded by ``search_window``, for a row whose
    normalized text matches; falls back to ``anchor.row`` unchanged when
    nothing matches.
    """
    if content_digest is not None and content_digest == anchor.content_digest:
        return anchor.row

    if anchor.line_start_row_text is None:
        return anchor.row

    for distance in range(search_window + 1):
        for candidate in sorted({anchor.row - distance, anchor.row + distance}):
            if candidate < window_start:
                continue
            text = _text_at(row_texts, window_start, candidate)
            if text is None:
                continue
            if gutter_present and not _is_line_start(text):
                continue
            if _normalize_row(text) == anchor.line_start_row_text:
                return candidate + anchor.sub_offset

    return anchor.row


class AnchorStore:
    """Bounded LRU of per-page-slot scroll anchors."""

    def __init__(self, max_entries: int = 64) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[object, _ScrollAnchor] = OrderedDict()

    def get(self, key: object) -> _ScrollAnchor | None:
        """Return the stored anchor for *key*, or None if never captured."""
        anchor = self._entries.get(key)
        if anchor is not None:
            self._entries.move_to_end(key)
        return anchor

    def set(self, key: object, anchor: _ScrollAnchor) -> None:
        """Store *anchor* under *key*, evicting the oldest entry if full."""
        self._entries[key] = anchor
        self._entries.move_to_end(key)
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
