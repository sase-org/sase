"""Proportional heat strips for Footprint area rows."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.footprint.render._styles import (
    NOT_MEASURED_GLYPH,
    NOT_MEASURED_STYLE,
    RECENT_7D_GLYPH,
    RECENT_7D_STYLE,
    RECENT_30D_GLYPH,
    RECENT_30D_STYLE,
    RECENT_WINDOW_GLYPH,
    RECENT_WINDOW_STYLE,
    ZERO_GLYPH,
    ZERO_STYLE,
)


def heat_strip(area: dict[str, Any], *, width: int) -> Text:
    """Return a proportional hot-to-cold strip scaled to *width* cells."""
    width = max(4, int(width))
    total = max(0, int(area.get("total", 0) or 0))
    if total <= 0:
        return Text(ZERO_GLYPH * width, style=ZERO_STYLE)
    buckets: list[tuple[int, str, str]] = [
        (max(0, int(area.get("recency_7d", 0) or 0)), RECENT_7D_GLYPH, RECENT_7D_STYLE),
        (
            max(0, int(area.get("recency_30d", 0) or 0)),
            RECENT_30D_GLYPH,
            RECENT_30D_STYLE,
        ),
        (
            max(0, int(area.get("recency_window", 0) or 0)),
            RECENT_WINDOW_GLYPH,
            RECENT_WINDOW_STYLE,
        ),
        (max(0, int(area.get("recency_none", 0) or 0)), ZERO_GLYPH, ZERO_STYLE),
        (
            max(0, int(area.get("recency_not_measured", 0) or 0)),
            NOT_MEASURED_GLYPH,
            NOT_MEASURED_STYLE,
        ),
    ]
    counts = [count for count, _, _ in buckets]
    if sum(counts) <= 0:
        return Text(ZERO_GLYPH * width, style=ZERO_STYLE)
    cells = _largest_remainder(counts, total, width)
    _ensure_visible_minimum(counts, cells)
    text = Text()
    for count_cells, (_, glyph, style) in zip(cells, buckets, strict=True):
        if count_cells > 0:
            text.append(glyph * count_cells, style=style)
    return text


def _ensure_visible_minimum(counts: list[int], cells: list[int]) -> None:
    """Give every nonzero bucket at least one cell, taken from the largest.

    A single used feature in a large area stays visible instead of rounding
    to zero; the strip stays proportional otherwise.
    """
    for index, (count, cell_count) in enumerate(zip(counts, cells, strict=True)):
        if count > 0 and cell_count == 0:
            donor = max(range(len(cells)), key=lambda i: cells[i])
            if cells[donor] > 1:
                cells[donor] -= 1
                cells[index] += 1


def _largest_remainder(counts: list[int], total: int, width: int) -> list[int]:
    """Split *width* cells across *counts* proportionally to *total*."""
    if total <= 0 or width <= 0:
        return [0] * len(counts)
    quotas = [count / total * width for count in counts]
    cells = [int(quota) for quota in quotas]
    remainder = width - sum(cells)
    order = sorted(
        range(len(counts)),
        key=lambda index: (quotas[index] - cells[index], counts[index]),
        reverse=True,
    )
    index = 0
    while remainder > 0 and order:
        cells[order[index % len(order)]] += 1
        remainder -= 1
        index += 1
    return cells


__all__ = ["heat_strip"]
