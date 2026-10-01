"""Generic list model for the ``@`` timeline picker modal.

No memory-specific vocabulary belongs here: rows are plain mappings
with ``hidden`` and ``haystack`` keys that the memory-side builder
fills in. The modal renders only one window of rows, so timelines
with hundreds of versions never cost more than a screen of
formatting per keypress.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Mapping


def visible_rows(
    rows: tuple[Mapping[str, Any], ...], *, show_hidden: bool
) -> tuple[Mapping[str, Any], ...]:
    """Return the rows the picker lists (hidden rows need ``.``)."""
    if show_hidden:
        return rows
    return tuple(row for row in rows if not bool(row.get("hidden", False)))


def filter_rows(
    rows: tuple[Mapping[str, Any], ...], query: str
) -> tuple[Mapping[str, Any], ...]:
    """Filter rows to those matching every whitespace-separated token.

    The query runs over each row's prebuilt ``haystack`` (section,
    agent, bead, subject, and words) — never bodies, so filtering
    stays instant on large timelines.
    """
    tokens = [token for token in query.lower().split() if token]
    if not tokens:
        return rows
    return tuple(
        row
        for row in rows
        if all(token in str(row.get("haystack", "")) for token in tokens)
    )


def picker_window(total: int, cursor: int, height: int) -> tuple[int, int]:
    """Return the ``(start, end)`` slice rendered around *cursor*."""
    if total <= 0 or height <= 0:
        return (0, 0)
    pinned = max(0, min(cursor, total - 1))
    half = max(height // 2, 0)
    start = max(0, min(pinned - half, max(total - height, 0)))
    return (start, min(total, start + max(height, 1)))


__all__ = ["filter_rows", "picker_window", "visible_rows"]
