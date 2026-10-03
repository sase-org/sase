"""Golden transition table for the shared PaneGrid split algebra.

The checked-in ``pane_grid_golden.txt`` renders every (state, key) pair as
reviewable spec: 17 states (seven geometries times each focus position)
times 10 keys. Regeneration is explicit and opt-in::

    SASE_UPDATE_PANE_GRID_GOLDEN=1 pytest tests/ace/tui/util/test_pane_grid.py

The default run compares against the checked-in table.
"""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.tui.util.pane_grid import (
    Axis,
    GridSpec,
    Pair,
    PaneGrid,
    close_focused,
    cycle_focus,
    fits,
    focus_pane,
    free_pane_id,
    geometry,
    grid_spec,
    main_pane,
    other_target,
    pane_rects,
    position_glyph,
    position_name,
    press_split,
    step_ratio,
    swap_focused,
    turn,
)

_GOLDEN = Path(__file__).with_name("pane_grid_golden.txt")
_REGENERATE = os.environ.get("SASE_UPDATE_PANE_GRID_GOLDEN") == "1"

_GEO_CODE = {
    "single": "S",
    "R2": "R2",
    "C2": "C2",
    "R3-main-top": "R3t",
    "R3-main-bottom": "R3b",
    "C3-main-left": "C3l",
    "C3-main-right": "C3r",
}


def _fmt_state(g: PaneGrid) -> str:
    panes = " ".join(f"{p}*" if p == g.focused else str(p) for p in g.panes)
    text = f"{_GEO_CODE[geometry(g).value]}[{panes}]o{g.ratio}"
    if g.pair is not None:
        text += f"i{g.pair.ratio}"
    text += f"m{''.join(str(p) for p in g.recent)}"
    return text


def _two_panes(
    axis: Axis, focused: int, ratio: int, pair_ratio: int | None = None
) -> PaneGrid:
    panes = (0, 1)
    other = 1 - focused
    return PaneGrid(
        panes=panes,
        focused=focused,
        axis=axis,
        ratio=ratio,
        recent=(focused, other),
    )


def _three_panes(
    axis: Axis, region: int, focused: int, ratio: int, pair_ratio: int
) -> PaneGrid:
    panes = (0, 1, 2)
    rest = [p for p in panes if p != focused]
    return PaneGrid(
        panes=panes,
        focused=focused,
        axis=axis,
        ratio=ratio,
        pair=Pair(region=region, ratio=pair_ratio),
        recent=(focused, *rest),
    )


def _states() -> list[PaneGrid]:
    states = [
        PaneGrid(),
        _two_panes(Axis.ROWS, 0, 50),
        _two_panes(Axis.ROWS, 1, 70),
        _two_panes(Axis.COLS, 0, 30),
        _two_panes(Axis.COLS, 1, 50),
    ]
    for region, axis in (
        (1, Axis.ROWS),
        (0, Axis.ROWS),
        (1, Axis.COLS),
        (0, Axis.COLS),
    ):
        ratios = (70, 30) if region == 1 else (30, 70)
        for focused in (0, 1, 2):
            states.append(_three_panes(axis, region, focused, *ratios))
    assert len(states) == 17
    return states


def _apply_key(g: PaneGrid, key: str) -> PaneGrid:
    new_id = free_pane_id(g)
    if key == "\\":
        return press_split(g, Axis.ROWS, new_id if new_id is not None else -1)
    if key == "|":
        return press_split(g, Axis.COLS, new_id if new_id is not None else -1)
    if key == "f+":
        return cycle_focus(g, 1)
    if key == "f-":
        return cycle_focus(g, -1)
    if key == "s+":
        return swap_focused(g, 1)
    if key == "s-":
        return swap_focused(g, -1)
    if key == "x":
        return close_focused(g)
    if key == "t":
        return turn(g)
    if key == "r+":
        return step_ratio(g, True)
    assert key == "r-"
    return step_ratio(g, False)


_KEYS = ["\\", "|", "f+", "f-", "s+", "s-", "x", "t", "r+", "r-"]


def _render_table(states: list[PaneGrid], keys: list[str]) -> str:
    lines = [
        "# PaneGrid golden transition table.",
        "# Regenerate with SASE_UPDATE_PANE_GRID_GOLDEN=1; the default run compares.",
        "# Row: <before> <key> => <after>. Focused pane is marked `*`;",
        "# o = outer ratio, i = pair ratio, m = MRU order.",
    ]
    for state in states:
        before = _fmt_state(state)
        for key in keys:
            lines.append(f"{before} {key} => {_fmt_state(_apply_key(state, key))}")
    return "\n".join(lines) + "\n"


def _check_or_write(path: Path, rendered: str) -> None:
    if _REGENERATE:
        path.write_text(rendered)
        return
    assert path.exists(), (
        f"missing golden file {path.name}; regenerate with opt-in flag"
    )
    assert path.read_text() == rendered, (
        f"{path.name} drifted; inspect the diff, then regenerate with the opt-in flag"
    )


def test_golden_transition_table() -> None:
    """Every (state, key) pair matches the checked-in transition table."""
    _check_or_write(_GOLDEN, _render_table(_states(), _KEYS))


def test_same_key_unsplit_keeps_focused_pane() -> None:
    """Same-key unsplit keeps the focused pane (decision A3)."""
    state = _two_panes(Axis.ROWS, 1, 50)
    assert press_split(state, Axis.ROWS, 2).panes == (1,)
    state = _two_panes(Axis.COLS, 0, 50)
    assert press_split(state, Axis.COLS, 2).panes == (0,)


def test_nest_keeps_unfocused_pane_in_place() -> None:
    """Nesting splits the focused pane; the unfocused pane becomes main."""
    top_focused = _two_panes(Axis.ROWS, 0, 50)
    nested = press_split(top_focused, Axis.COLS, 2)
    assert geometry(nested).value == "R3-main-bottom"
    assert nested.panes == (0, 2, 1)
    assert main_pane(nested) == 1
    bottom_focused = _two_panes(Axis.ROWS, 1, 50)
    nested = press_split(bottom_focused, Axis.COLS, 2)
    assert geometry(nested).value == "R3-main-top"
    assert nested.panes == (0, 1, 2)
    assert main_pane(nested) == 0


def test_erase_keeps_side_and_pair_ratio() -> None:
    """Erasing keeps the side in focus and the pair ratio (decision A2)."""
    state = _three_panes(Axis.ROWS, 1, 2, 70, 30)
    erased = press_split(state, Axis.ROWS, 2)
    assert geometry(erased).value == "C2"
    assert erased.panes == (1, 2)
    assert erased.ratio == 30
    main_focused = _three_panes(Axis.ROWS, 1, 0, 70, 30)
    assert press_split(main_focused, Axis.ROWS, 2).panes == (0,)


def test_close_is_inverse_of_split() -> None:
    """close after split returns ratios, focus, and MRU exactly."""
    single = PaneGrid()
    for axis in (Axis.ROWS, Axis.COLS):
        assert close_focused(press_split(single, axis, 1)) == single
    two = _two_panes(Axis.ROWS, 0, 70)
    nested = press_split(two, Axis.COLS, 2)
    assert close_focused(nested) == two


def test_mru_bookkeeping() -> None:
    """Focus fronts MRU; close drops the pane; swap/turn leave MRU alone."""
    state = _three_panes(Axis.ROWS, 1, 0, 50, 50)
    assert focus_pane(state, 2).recent == (2, 0, 1)
    assert other_target(state) == 1
    assert close_focused(_three_panes(Axis.ROWS, 1, 2, 50, 50)).recent == (0, 1)
    assert swap_focused(state, 1).recent == state.recent
    assert turn(state).recent == state.recent


def test_positions_name_targets_only() -> None:
    """Position names and glyphs cover every slot; lone panes name nothing."""
    state = _three_panes(Axis.COLS, 0, 0, 50, 50)
    assert [position_name(state, p) for p in state.panes] == [
        "top-left",
        "bottom-left",
        "right",
    ]
    assert [position_glyph(state, p) for p in state.panes] == [
        "\u25f0",
        "\u25f1",
        "\u25e8",
    ]
    assert position_name(PaneGrid(), 0) == ""
    assert position_glyph(PaneGrid(), 0) == ""
    assert position_name(state, 9) == ""


def test_rects_use_pager_floor_rule() -> None:
    """First region takes total*ratio//100, the second takes the rest."""
    state = _two_panes(Axis.ROWS, 0, 30)
    assert pane_rects(state, 100, 10) == {0: (0, 0, 100, 3), 1: (0, 3, 100, 7)}
    assert fits(
        _three_panes(Axis.ROWS, 1, 0, 50, 50), 120, 40, min_width=32, min_height=7
    )
    assert not fits(
        _three_panes(Axis.ROWS, 1, 0, 50, 50), 60, 10, min_width=32, min_height=7
    )


def test_grid_spec_t_shape_spans_and_dom_order() -> None:
    """Main spans two cells; main-right DOM order is B A C, not reading."""
    main_right = _three_panes(Axis.COLS, 0, 0, 50, 50)
    spec = grid_spec(main_right)
    assert isinstance(spec, GridSpec)
    assert spec.columns == (50, 50)
    assert spec.cells[2] == (1, 0, 1, 2)
    assert spec.dom_order == (0, 2, 1)
    main_top = _three_panes(Axis.ROWS, 1, 0, 70, 30)
    spec = grid_spec(main_top)
    assert spec.rows == (70, 30)
    assert spec.columns == (30, 70)
    assert spec.cells[0] == (0, 0, 2, 1)
