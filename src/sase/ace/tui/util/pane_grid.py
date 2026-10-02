"""Shared pure pane-split algebra for the Agents deck and the pager.

One closed model with seven geometries and at most three panes. Every
transition is total: invalid input, or a key that is inert in the current
state, returns an equal grid. Nothing raises.

Stdlib only: no Textual, Rich, deck, or pager imports.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum

RATIO_STEPS: tuple[int, ...] = (30, 50, 70)
MAX_PANES = 3

#: Pane rectangle as ``(x, y, width, height)`` in cells.
PaneRect = tuple[int, int, int, int]

#: Grid cell as ``(column, row, column_span, row_span)``.
GridCell = tuple[int, int, int, int]


class Axis(StrEnum):
    """Outer split axis, named by the divider the split key draws."""

    ROWS = "rows"  # stacked, drawn by `\`
    COLS = "cols"  # side by side, drawn by `|`


class Geometry(StrEnum):
    """The seven closed geometries."""

    SINGLE = "single"
    R2 = "R2"  # two panes stacked
    C2 = "C2"  # two panes side by side
    R3_MAIN_TOP = "R3-main-top"
    R3_MAIN_BOTTOM = "R3-main-bottom"
    C3_MAIN_LEFT = "C3-main-left"
    C3_MAIN_RIGHT = "C3-main-right"


@dataclass(frozen=True, slots=True)
class Pair:
    """The inner two-pane split of a three-pane grid."""

    region: int  # outer region holding the pair: 0 = top/left, 1 = bottom/right
    ratio: int = 50  # first pair member's share


@dataclass(frozen=True, slots=True)
class PaneGrid:
    """One immutable split arrangement.

    ``panes`` holds the visible stable pane IDs in reading order (outer
    first region, then second; within the pair, first member then second).
    ``focused`` is a member of ``panes``. ``axis`` is the outer split axis
    (``None`` exactly when single) and ``ratio`` the outer first region's
    share. ``pair`` is set exactly when three panes are visible. ``recent``
    is an MRU permutation of ``panes`` with the focused pane first.
    """

    panes: tuple[int, ...] = (0,)
    focused: int = 0
    axis: Axis | None = None
    ratio: int = 50
    pair: Pair | None = None
    recent: tuple[int, ...] = (0,)


@dataclass(frozen=True, slots=True)
class GridSpec:
    """A direct mapping onto a Textual ``layout: grid`` container.

    ``columns``/``rows`` are ``fr`` track weights, ``cells`` maps each pane
    ID to ``(column, row, column_span, row_span)``, and ``dom_order`` is the
    row-major order of each pane's top-left cell (which is not reading
    order: main-right reads ``B A C``).
    """

    columns: tuple[int, ...]
    rows: tuple[int, ...]
    cells: dict[int, GridCell]
    dom_order: tuple[int, ...]

    def cell(self, pane_id: int) -> GridCell:
        """Return the grid cell for *pane_id*."""
        return self.cells[pane_id]


def _other_axis(axis: Axis) -> Axis:
    return Axis.COLS if axis is Axis.ROWS else Axis.ROWS


def geometry(g: PaneGrid) -> Geometry:
    """Return the closed geometry of *g* (lenient on malformed input)."""
    n = len(g.panes)
    if n <= 1:
        return Geometry.SINGLE
    if n == 2:
        return Geometry.R2 if g.axis is Axis.ROWS else Geometry.C2
    region = g.pair.region if g.pair is not None else 1
    if g.axis is Axis.COLS:
        return Geometry.C3_MAIN_LEFT if region == 1 else Geometry.C3_MAIN_RIGHT
    return Geometry.R3_MAIN_TOP if region == 1 else Geometry.R3_MAIN_BOTTOM


def main_pane(g: PaneGrid) -> int | None:
    """Return the full-span main pane ID, or ``None`` unless three panes."""
    if len(g.panes) != 3 or g.pair is None:
        return None
    return g.panes[0] if g.pair.region == 1 else g.panes[2]


def _pair_members(g: PaneGrid) -> tuple[int, int] | None:
    if len(g.panes) != 3 or g.pair is None:
        return None
    if g.pair.region == 1:
        return (g.panes[1], g.panes[2])
    return (g.panes[0], g.panes[1])


def free_pane_id(g: PaneGrid) -> int | None:
    """Return the lowest unused pane ID, or ``None`` when full."""
    for pane_id in range(MAX_PANES):
        if pane_id not in g.panes:
            return pane_id
    return None


def _refocus(g: PaneGrid, focused: int) -> PaneGrid:
    recent = (focused, *(p for p in g.recent if p != focused))
    return dataclasses.replace(g, focused=focused, recent=recent)


def focus_pane(g: PaneGrid, pane_id: int) -> PaneGrid:
    """Focus *pane_id*, moving it to the MRU front; unknown IDs are inert."""
    if pane_id not in g.panes:
        return g
    return _refocus(g, pane_id)


def cycle_focus(g: PaneGrid, step: int) -> PaneGrid:
    """Move focus *step* panes forward in reading order, wrapping."""
    if len(g.panes) < 2:
        return g
    index = g.panes.index(g.focused)
    return _refocus(g, g.panes[(index + step) % len(g.panes)])


def swap_focused(g: PaneGrid, step: int) -> PaneGrid:
    """Exchange the focused pane's content with the neighbour *step* away.

    Geometry and both ratios belong to slots and do not change; focus
    follows the content. ``recent`` is unchanged. A full cycle is inert.
    """
    n = len(g.panes)
    if n < 2:
        return g
    index = g.panes.index(g.focused)
    other = (index + step) % n
    if other == index:
        return g
    panes = list(g.panes)
    panes[index], panes[other] = panes[other], panes[index]
    return dataclasses.replace(g, panes=tuple(panes))


def turn(g: PaneGrid) -> PaneGrid:
    """Transpose any split; inert on a single pane, self-inverse."""
    if len(g.panes) < 2 or g.axis is None:
        return g
    return dataclasses.replace(g, axis=_other_axis(g.axis))


def _step_value(value: int, direction: int) -> int:
    steps = list(RATIO_STEPS)
    try:
        position = steps.index(value)
    except ValueError:
        position = min(range(len(steps)), key=lambda i: abs(steps[i] - value))
    position = max(0, min(len(steps) - 1, position + direction))
    return steps[position]


def step_ratio(g: PaneGrid, grow: bool) -> PaneGrid:
    """Grow (or shrink) the focused pane one ratio step, clamping silently.

    Steps the split that directly separates the focused pane from its
    sibling: the inner split for a pair pane, the outer split for the main
    pane or for either pane of a two-pane split.
    """
    if len(g.panes) < 2:
        return g
    members = _pair_members(g)
    main = main_pane(g)
    if members is not None and main is not None and g.pair is not None:
        if g.focused == main:
            main_region = 0 if g.pair.region == 1 else 1
            direction = 1 if (grow == (main_region == 0)) else -1
            return dataclasses.replace(g, ratio=_step_value(g.ratio, direction))
        first, _second = members
        direction = 1 if (grow == (g.focused == first)) else -1
        return dataclasses.replace(
            g,
            pair=Pair(region=g.pair.region, ratio=_step_value(g.pair.ratio, direction)),
        )
    index = g.panes.index(g.focused)
    direction = 1 if (grow == (index == 0)) else -1
    return dataclasses.replace(g, ratio=_step_value(g.ratio, direction))


def other_target(g: PaneGrid) -> int | None:
    """Return the MRU other pane, else the next pane in reading order."""
    if len(g.panes) < 2:
        return None
    for pane_id in g.recent:
        if pane_id != g.focused and pane_id in g.panes:
            return pane_id
    index = g.panes.index(g.focused)
    return g.panes[(index + 1) % len(g.panes)]


def _erase(g: PaneGrid) -> PaneGrid:
    """Collapse a three-pane grid along its outer divider (nest-off path)."""
    main = main_pane(g)
    members = _pair_members(g)
    if main is None or members is None or g.pair is None or g.axis is None:
        return g
    if g.focused == main:
        return PaneGrid(panes=(main,), focused=main, recent=(main,))
    inner = _other_axis(g.axis)
    return PaneGrid(
        panes=members,
        focused=g.focused,
        axis=inner,
        ratio=g.pair.ratio,
        recent=tuple(p for p in g.recent if p in members),
    )


def press_split(g: PaneGrid, axis: Axis, new_id: int, *, nest: bool = True) -> PaneGrid:
    """Apply the one split-key rule for a divider of kind *axis*.

    From a single pane, draw the divider through the focused pane: the new
    pane opens below (stacked) or right (side by side) and takes focus at
    50/50. From a two-pane split, the same-axis key erases the divider and
    keeps the focused pane; the other-axis key nests a third pane (the
    focused pane splits, the new pane takes focus, the unfocused pane
    becomes main without moving or resizing) or, with ``nest=False``,
    turns the split. From three panes, the outer-axis key erases the
    full-span divider (focus in the pair keeps the pair; focus on main
    keeps main) and the other key turns the layout.

    ``nest=False`` is the flag-off branch and never yields three panes.
    Paths that create no pane ignore *new_id*; the others need an unused ID
    in ``range(MAX_PANES)``.
    """
    if axis not in (Axis.ROWS, Axis.COLS):
        return g
    n = len(g.panes)
    if n <= 1:
        focused = g.panes[0] if g.panes else 0
        if new_id in g.panes or not 0 <= new_id < MAX_PANES:
            return g
        return PaneGrid(
            panes=(focused, new_id),
            focused=new_id,
            axis=axis,
            recent=(new_id, focused),
        )
    if n == 2:
        if axis == g.axis:
            return PaneGrid(panes=(g.focused,), focused=g.focused, recent=(g.focused,))
        if not nest:
            return turn(g)
        if new_id in g.panes or not 0 <= new_id < MAX_PANES:
            return g
        index = g.panes.index(g.focused)
        unfocused = g.panes[1 - index]
        if index == 0:
            panes = (g.focused, new_id, unfocused)
        else:
            panes = (unfocused, g.focused, new_id)
        return PaneGrid(
            panes=panes,
            focused=new_id,
            axis=g.axis,
            ratio=g.ratio,
            pair=Pair(region=index, ratio=50),
            recent=(new_id, *g.recent),
        )
    if axis == g.axis or not nest:
        return _erase(g)
    return turn(g)


def close_focused(g: PaneGrid) -> PaneGrid:
    """Close the focused pane; inert on a single pane.

    A closed pair member's sibling takes over its space (two-pane split on
    the outer axis, outer ratio kept); a closed main pane leaves the pair
    (two-pane split on the inner axis, pair ratio kept); a two-pane close
    leaves a single pane. Focus goes to the MRU survivor. This is the exact
    inverse of split from one- and two-pane grids.
    """
    if len(g.panes) == 2:
        survivor = g.panes[1] if g.focused == g.panes[0] else g.panes[0]
        return PaneGrid(panes=(survivor,), focused=survivor, recent=(survivor,))
    if len(g.panes) != 3 or g.pair is None or g.axis is None:
        return g
    main = main_pane(g)
    members = _pair_members(g)
    if main is None or members is None:
        return g
    recent = tuple(p for p in g.recent if p != g.focused)
    focus = recent[0] if recent else g.focused
    if g.focused == main:
        inner = _other_axis(g.axis)
        return PaneGrid(
            panes=members, focused=focus, axis=inner, ratio=g.pair.ratio, recent=recent
        )
    sibling = members[1] if g.focused == members[0] else members[0]
    if g.pair.region == 0:
        panes = (sibling, main)
    else:
        panes = (main, sibling)
    return PaneGrid(
        panes=panes, focused=focus, axis=g.axis, ratio=g.ratio, recent=recent
    )


def pane_rects(g: PaneGrid, width: int, height: int) -> dict[int, PaneRect]:
    """Map each pane ID to ``(x, y, w, h)`` with pager ``split_fits`` floors.

    The first region takes ``total * ratio // 100`` cells and the second
    takes the rest, so rects tile ``width`` x ``height`` exactly.
    """
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        return dict.fromkeys(g.panes, (0, 0, 0, 0))

    def split_total(total: int, ratio: int) -> tuple[int, int]:
        first = total * int(ratio) // 100
        return first, total - first

    if len(g.panes) <= 1 or g.axis is None:
        pane = g.panes[0] if g.panes else g.focused
        return {pane: (0, 0, width, height)}
    if len(g.panes) == 2:
        first, second = split_total(height if g.axis is Axis.ROWS else width, g.ratio)
        if g.axis is Axis.ROWS:
            return {
                g.panes[0]: (0, 0, width, first),
                g.panes[1]: (0, first, width, second),
            }
        return {
            g.panes[0]: (0, 0, first, height),
            g.panes[1]: (first, 0, second, height),
        }
    members = _pair_members(g)
    main = main_pane(g)
    pair_ratio = g.pair.ratio if g.pair is not None else 50
    region = g.pair.region if g.pair is not None else 1
    if members is None or main is None:
        return dict.fromkeys(g.panes, (0, 0, 0, 0))
    if g.axis is Axis.ROWS:
        top, bottom = split_total(height, g.ratio)
        left, right = split_total(width, pair_ratio)
        if region == 0:
            return {
                members[0]: (0, 0, left, top),
                members[1]: (left, 0, right, top),
                main: (0, top, width, bottom),
            }
        return {
            main: (0, 0, width, top),
            members[0]: (0, top, left, bottom),
            members[1]: (left, top, right, bottom),
        }
    left, right = split_total(width, g.ratio)
    top, bottom = split_total(height, pair_ratio)
    if region == 0:
        return {
            members[0]: (0, 0, left, top),
            members[1]: (0, top, left, bottom),
            main: (left, 0, right, height),
        }
    return {
        main: (0, 0, left, height),
        members[0]: (left, 0, right, top),
        members[1]: (left, top, right, bottom),
    }


def fits(
    g: PaneGrid, width: int, height: int, *, min_width: int, min_height: int
) -> bool:
    """Return whether every pane meets the minimum extent in this area."""
    if len(g.panes) <= 1:
        return True
    rects = pane_rects(g, width, height)
    return all(w >= min_width and h >= min_height for (_, _, w, h) in rects.values())


_POSITION_TABLE: dict[tuple[Geometry, int], tuple[str, str]] = {
    (Geometry.R2, 0): ("top", "\u2b12"),
    (Geometry.R2, 1): ("bottom", "\u2b13"),
    (Geometry.C2, 0): ("left", "\u25e7"),
    (Geometry.C2, 1): ("right", "\u25e8"),
    (Geometry.R3_MAIN_TOP, 0): ("top", "\u2b12"),
    (Geometry.R3_MAIN_TOP, 1): ("bottom-left", "\u25f1"),
    (Geometry.R3_MAIN_TOP, 2): ("bottom-right", "\u25f2"),
    (Geometry.R3_MAIN_BOTTOM, 0): ("top-left", "\u25f0"),
    (Geometry.R3_MAIN_BOTTOM, 1): ("top-right", "\u25f3"),
    (Geometry.R3_MAIN_BOTTOM, 2): ("bottom", "\u2b13"),
    (Geometry.C3_MAIN_LEFT, 0): ("left", "\u25e7"),
    (Geometry.C3_MAIN_LEFT, 1): ("top-right", "\u25f3"),
    (Geometry.C3_MAIN_LEFT, 2): ("bottom-right", "\u25f2"),
    (Geometry.C3_MAIN_RIGHT, 0): ("top-left", "\u25f0"),
    (Geometry.C3_MAIN_RIGHT, 1): ("bottom-left", "\u25f1"),
    (Geometry.C3_MAIN_RIGHT, 2): ("right", "\u25e8"),
}


def _position_entry(g: PaneGrid, pane_id: int) -> tuple[str, str]:
    try:
        slot = g.panes.index(pane_id)
    except ValueError:
        return ("", "")
    return _POSITION_TABLE.get((geometry(g), slot), ("", ""))


def position_name(g: PaneGrid, pane_id: int) -> str:
    """Name a pane's position (``top-left``, ``right``, ...).

    Names exist to disambiguate panes, so a single pane and unknown IDs
    yield ``""``.
    """
    return _position_entry(g, pane_id)[0]


def position_glyph(g: PaneGrid, pane_id: int) -> str:
    """Return the one-cell position glyph for zoom chips and picker hints."""
    return _position_entry(g, pane_id)[1]


def grid_spec(g: PaneGrid) -> GridSpec:
    """Map *g* onto Textual grid tracks, per-pane cells, and DOM order."""
    if len(g.panes) <= 1 or g.axis is None:
        pane = g.panes[0] if g.panes else g.focused
        return GridSpec(
            columns=(1,), rows=(1,), cells={pane: (0, 0, 1, 1)}, dom_order=(pane,)
        )
    if len(g.panes) == 2:
        first, second = g.ratio, 100 - g.ratio
        if g.axis is Axis.ROWS:
            cells = {g.panes[0]: (0, 0, 1, 1), g.panes[1]: (0, 1, 1, 1)}
            return GridSpec(
                columns=(1,),
                rows=(first, second),
                cells=cells,
                dom_order=tuple(g.panes),
            )
        cells = {g.panes[0]: (0, 0, 1, 1), g.panes[1]: (1, 0, 1, 1)}
        return GridSpec(
            columns=(first, second), rows=(1,), cells=cells, dom_order=tuple(g.panes)
        )
    members = _pair_members(g)
    main = main_pane(g)
    pair_ratio = g.pair.ratio if g.pair is not None else 50
    region = g.pair.region if g.pair is not None else 1
    if members is None or main is None:
        panes = tuple(g.panes)
        cells = dict.fromkeys(panes, (0, 0, 1, 1))
        return GridSpec(columns=(1,), rows=(1,), cells=cells, dom_order=panes)
    first, second = g.ratio, 100 - g.ratio
    inner_first, inner_second = pair_ratio, 100 - pair_ratio
    first_member, second_member = members
    if g.axis is Axis.ROWS:
        if region == 0:
            cells = {
                first_member: (0, 0, 1, 1),
                second_member: (1, 0, 1, 1),
                main: (0, 1, 2, 1),
            }
        else:
            cells = {
                main: (0, 0, 2, 1),
                first_member: (0, 1, 1, 1),
                second_member: (1, 1, 1, 1),
            }
        spec = GridSpec(
            columns=(inner_first, inner_second),
            rows=(first, second),
            cells=cells,
            dom_order=tuple(g.panes),
        )
    else:
        if region == 0:
            cells = {
                first_member: (0, 0, 1, 1),
                second_member: (0, 1, 1, 1),
                main: (1, 0, 1, 2),
            }
        else:
            cells = {
                main: (0, 0, 1, 2),
                first_member: (1, 0, 1, 1),
                second_member: (1, 1, 1, 1),
            }
        spec = GridSpec(
            columns=(first, second),
            rows=(inner_first, inner_second),
            cells=cells,
            dom_order=tuple(g.panes),
        )
    order = tuple(sorted(spec.dom_order, key=lambda p: (cells[p][1], cells[p][0])))
    return dataclasses.replace(spec, dom_order=order)


__all__ = [
    "MAX_PANES",
    "RATIO_STEPS",
    "Axis",
    "Geometry",
    "GridCell",
    "GridSpec",
    "Pair",
    "PaneGrid",
    "PaneRect",
    "close_focused",
    "cycle_focus",
    "fits",
    "focus_pane",
    "free_pane_id",
    "geometry",
    "grid_spec",
    "main_pane",
    "other_target",
    "pane_rects",
    "position_glyph",
    "position_name",
    "press_split",
    "step_ratio",
    "swap_focused",
    "turn",
]
