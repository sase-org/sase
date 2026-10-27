"""Deterministic capacity-gauge geometry for the shared capacity view."""

from __future__ import annotations

import math

from ._capacity_view import CapacityGaugeCell, MachineCapacityView

_USED = "█"
_FREE = "░"
_UNKNOWN = "╱"
_LIMIT = "┃"
_SPACE = " "
_EPS = 1e-9


def capacity_gauge_cells(
    view: MachineCapacityView, width: int
) -> tuple[CapacityGaugeCell, ...]:
    """Return one cell per column of a *width*-wide gauge for *view*."""
    occupied = float(view.occupied)
    limit = float(view.limit)
    if (
        width < 8
        or limit <= 0
        or not math.isfinite(occupied)
        or not math.isfinite(limit)
    ):
        return ()
    span = max(limit, occupied)
    if not math.isfinite(span) or span <= 0:
        return ()
    units = math.ceil(span - _EPS)
    if units <= 0:
        return ()
    invalid = bool(view.admission_blocked) and not view.accounting_unavailable
    cumulative = _charged_cumulative(view, invalid)
    over = occupied > limit + _EPS
    slot_w = (width - (units - 1)) // units
    if units <= 24 and slot_w >= 2:
        return _slot_cells(
            width=width,
            units=units,
            slot_w=slot_w,
            occupied=occupied,
            limit=limit,
            over=over,
            invalid=invalid,
            cumulative=cumulative,
        )
    return _continuous_cells(
        width=width,
        span=span,
        occupied=occupied,
        limit=limit,
        over=over,
        invalid=invalid,
        cumulative=cumulative,
    )


def _charged_cumulative(view: MachineCapacityView, invalid: bool) -> tuple[float, ...]:
    if invalid:
        return ()
    total = 0.0
    points = [0.0]
    for row in view.charged:
        total += float(row.charged_weight)
        points.append(total)
    return tuple(points)


def _slot_cells(
    *,
    width: int,
    units: int,
    slot_w: int,
    occupied: float,
    limit: float,
    over: bool,
    invalid: bool,
    cumulative: tuple[float, ...],
) -> tuple[CapacityGaugeCell, ...]:
    limit_after = math.ceil(limit) - 1 if over else None
    cells: list[CapacityGaugeCell] = []
    for index in range(units):
        for offset in range(slot_w):
            position = index + (offset + 0.5) / slot_w
            cells.append(_unit_cell(position, occupied, limit, invalid, cumulative))
        if index < units - 1:
            if over and index == limit_after:
                cells.append(CapacityGaugeCell(_LIMIT, "limit", None))
            else:
                cells.append(CapacityGaugeCell(_SPACE, "gap", None))
    leftover = width - len(cells)
    cells.extend(CapacityGaugeCell(_SPACE, "beyond", None) for _ in range(leftover))
    return tuple(cells)


def _continuous_cells(
    *,
    width: int,
    span: float,
    occupied: float,
    limit: float,
    over: bool,
    invalid: bool,
    cumulative: tuple[float, ...],
) -> tuple[CapacityGaugeCell, ...]:
    if not over:
        return tuple(
            _unit_cell(
                (index + 0.5) / width * span,
                occupied,
                limit,
                invalid,
                cumulative,
            )
            for index in range(width)
        )
    content = width - 1
    insert_at = round(limit / span * content)
    cells: list[CapacityGaugeCell] = []
    content_index = 0
    for index in range(width):
        if index == insert_at:
            cells.append(CapacityGaugeCell(_LIMIT, "limit", None))
            continue
        position = (content_index + 0.5) / content * span
        cells.append(_unit_cell(position, occupied, limit, invalid, cumulative))
        content_index += 1
    return tuple(cells)


def _unit_cell(
    position: float,
    occupied: float,
    limit: float,
    invalid: bool,
    cumulative: tuple[float, ...],
) -> CapacityGaugeCell:
    owner = _owner(position, cumulative)
    if position <= occupied and position > limit:
        return CapacityGaugeCell(_USED, "over", owner)
    if position <= occupied:
        return CapacityGaugeCell(_USED, "used", owner)
    if invalid and position <= limit:
        return CapacityGaugeCell(_UNKNOWN, "unknown", None)
    if position <= limit:
        return CapacityGaugeCell(_FREE, "free", None)
    return CapacityGaugeCell(_SPACE, "beyond", None)


def _owner(position: float, cumulative: tuple[float, ...]) -> int | None:
    if len(cumulative) < 2:
        return None
    for index in range(len(cumulative) - 1):
        if cumulative[index] < position <= cumulative[index + 1]:
            return index
    return None
