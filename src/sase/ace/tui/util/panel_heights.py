"""Shared stacked-panel height allocation for the ACE TUI.

Both the Agents tribe panels and the Services side panels stack bordered
lists in one container. This module holds the single allocation recipe so
the two call sites cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.css.scalar import Scalar, Unit


@dataclass(frozen=True)
class PanelHeight:
    """One panel's allocated height."""

    value: float
    unit: Literal["cells", "fr"]

    def to_scalar(self) -> Scalar:
        """Build the Textual height scalar for this allocation."""
        if self.unit == "cells":
            return Scalar(float(self.value), Unit.CELLS, Unit.HEIGHT)
        return Scalar(float(self.value), Unit.FRACTION, Unit.HEIGHT)


def allocate_panel_heights(
    content_rows: list[int],
    collapsed: list[bool],
    container_height: int,
    *,
    filler_idx: int,
) -> list[PanelHeight] | None:
    """Allocate one height per panel for a stacked panel container.

    Args:
        content_rows: Selectable content rows per panel (options for
            Agents, rendered lines for Services).
        collapsed: Whether each panel is collapsed to its border.
        container_height: Available container height in cells.
        filler_idx: Panel that absorbs spare rows (``1fr``) when
            everything fits.

    Returns:
        One :class:`PanelHeight` per panel, or ``None`` when the
        container height is still unknown (first paint, hidden tab).
    """
    if not content_rows:
        return []
    if not container_height:
        return None
    border_rows = 2
    counts = [max(0, int(rows)) for rows in content_rows]
    flags = [
        bool(collapsed[idx]) if idx < len(collapsed) else False
        for idx in range(len(counts))
    ]
    natural_heights = [
        border_rows if flags[idx] else count + border_rows
        for idx, count in enumerate(counts)
    ]
    separator_rows = max(0, len(counts) - 1)
    total_natural = sum(natural_heights) + separator_rows

    def cell_height(rows: float) -> PanelHeight:
        return PanelHeight(value=float(rows), unit="cells")

    def fraction_height(idx: int) -> PanelHeight:
        return PanelHeight(value=float(counts[idx] + 1), unit="fr")

    if total_natural <= container_height:
        # A collapsed filler is no filler at all: when every panel is
        # collapsed the original recipe sized each one in cells.
        filler_expanded = 0 <= filler_idx < len(flags) and not flags[filler_idx]
        return [
            PanelHeight(value=1.0, unit="fr")
            if filler_expanded and idx == filler_idx
            else cell_height(float(natural))
            for idx, natural in enumerate(natural_heights)
        ]

    content_budget = max(0, container_height - separator_rows)
    min_heights = [
        border_rows if flags[idx] else border_rows + min(count, 2)
        for idx, count in enumerate(counts)
    ]
    if content_budget < sum(min_heights):
        return [
            cell_height(float(border_rows)) if flags[idx] else fraction_height(idx)
            for idx in range(len(counts))
        ]

    fixed_heights: dict[int, float] = {
        idx: float(border_rows)
        for idx, is_collapsed in enumerate(flags)
        if is_collapsed
    }
    fixed_total = sum(fixed_heights.values())
    candidates = [idx for idx in range(len(counts)) if idx not in fixed_heights]
    for idx in sorted(candidates, key=lambda i: (natural_heights[i], i)):
        remaining_min = sum(
            min_heights[other]
            for other in range(len(counts))
            if other not in fixed_heights and other != idx
        )
        if fixed_total + natural_heights[idx] + remaining_min <= content_budget:
            fixed_heights[idx] = float(natural_heights[idx])
            fixed_total += natural_heights[idx]

    return [
        cell_height(fixed_heights[idx])
        if idx in fixed_heights
        else fraction_height(idx)
        for idx in range(len(counts))
    ]
