"""Deck three panels behind the ``three_pane_splits`` beta flag."""

from __future__ import annotations

import dataclasses
import json

from sase.ace.tui.models.agent_deck_persistence import (
    AgentsDeckStateSnapshot,
    _decode_agents_deck_state,
    _serialize_agents_deck_state,
    area_state_from_snapshot,
    snapshot_from_area_state,
    truncate_snapshot_to_two,
)
from sase.ace.tui.util.pane_grid import (
    Axis,
    Geometry,
    PaneGrid,
    close_focused,
    cycle_focus,
    focus_pane,
    geometry,
    main_pane,
    press_split,
    turn,
)
from sase.ace.tui.widgets.decks import layout as deck_layout
from sase.ace.tui.widgets.decks.layout import (
    MIN_DECK_PANEL_HEIGHT,
    MIN_DECK_PANEL_WIDTH,
    choose_new_panel,
    close_deck_panel,
    refuse_three_pane_key,
    refuse_turn,
    three_pane_splits_enabled,
    toggle_split,
    toggle_zoom,
)
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)
from sase.ace.tui.widgets.decks.picker import (
    deck_picker_other_hint,
    other_panel_target,
)
from sase.feature_flags import override_flags


def _two_panes(
    axis: Axis = Axis.ROWS, focused: int = 0, ratio: int = 50
) -> DeckAreaState:
    other = 1 - focused
    grid = PaneGrid(
        panes=(0, 1),
        focused=focused,
        axis=axis,
        ratio=ratio,
        recent=(focused, other),
    )
    return DeckAreaState(
        grid=grid,
        panels={0: DeckPanelState(DeckId.MAIN), 1: DeckPanelState(DeckId.FILES)},
    )


def _nest(state: DeckAreaState, target: DeckLayout) -> DeckAreaState:
    return toggle_split(state, target, DeckPanelState(DeckId.TOOLS), nest=True)


def test_flag_defaults_off_and_override_enables() -> None:
    assert three_pane_splits_enabled() is False
    with override_flags(three_pane_splits=True):
        assert three_pane_splits_enabled() is True
    assert three_pane_splits_enabled() is False


def test_nest_reaches_all_four_t_shapes() -> None:
    assert geometry(_nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT).grid) is (
        Geometry.R3_MAIN_BOTTOM
    )
    assert geometry(_nest(_two_panes(Axis.ROWS, 1), DeckLayout.LEFT_RIGHT).grid) is (
        Geometry.R3_MAIN_TOP
    )
    assert geometry(_nest(_two_panes(Axis.COLS, 0), DeckLayout.TOP_BOTTOM).grid) is (
        Geometry.C3_MAIN_RIGHT
    )
    assert geometry(_nest(_two_panes(Axis.COLS, 1), DeckLayout.TOP_BOTTOM).grid) is (
        Geometry.C3_MAIN_LEFT
    )


def test_nest_new_pane_takes_focus_and_main_does_not_move() -> None:
    before = _two_panes(Axis.ROWS, 0)
    nested = _nest(before, DeckLayout.LEFT_RIGHT)
    assert len(nested.grid.panes) == 3
    assert nested.grid.focused == 2
    assert nested.panels[2].deck is DeckId.TOOLS
    # The unfocused pane becomes main without moving or resizing.
    assert main_pane(nested.grid) == 1
    assert nested.grid.ratio == before.grid.ratio


def test_nest_flag_off_rotates_and_never_shows_third() -> None:
    state = _two_panes(Axis.ROWS, 0)
    rotated = toggle_split(
        state, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS), nest=False
    )
    assert len(rotated.grid.panes) == 2
    assert geometry(rotated.grid) is Geometry.C2


def test_erase_with_main_focused_keeps_main() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    main = main_pane(nested.grid)
    assert main is not None
    erased = toggle_split(
        dataclasses.replace(nested, grid=focus_pane(nested.grid, main)),
        DeckLayout.TOP_BOTTOM,
        nested.panels[main],
        nest=True,
    )
    assert len(erased.grid.panes) == 1
    assert erased.grid.focused == main


def test_erase_with_pair_focused_keeps_pair() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    pair_focus = nested.grid.panes[1]
    assert pair_focus != main_pane(nested.grid)
    erased = toggle_split(
        dataclasses.replace(nested, grid=focus_pane(nested.grid, pair_focus)),
        DeckLayout.TOP_BOTTOM,
        nested.panels[pair_focus],
        nest=True,
    )
    assert geometry(erased.grid) is Geometry.C2
    assert set(erased.grid.panes) == set(nested.grid.panes) - {main_pane(nested.grid)}


def test_turn_both_ways_is_self_inverse() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    turned = toggle_split(
        nested, DeckLayout.LEFT_RIGHT, nested.panels[nested.grid.focused], nest=True
    )
    assert geometry(turned.grid) is Geometry.C3_MAIN_RIGHT
    back = toggle_split(
        turned, DeckLayout.TOP_BOTTOM, turned.panels[turned.grid.focused], nest=True
    )
    assert back.grid == nested.grid


def test_close_each_of_three_panels() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    for pane_id in nested.grid.panes:
        closed = close_deck_panel(
            dataclasses.replace(nested, grid=focus_pane(nested.grid, pane_id))
        )
        assert len(closed.grid.panes) == 2
        assert pane_id not in closed.grid.panes
        assert pane_id not in closed.panels


def test_split_key_while_zoomed_only_restores() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    zoomed = toggle_zoom(nested)
    restored = toggle_split(
        zoomed, DeckLayout.LEFT_RIGHT, zoomed.panels[zoomed.grid.focused], nest=True
    )
    assert restored.grid == nested.grid


def test_fit_refusal_toast_and_state_unchanged() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    message = refuse_three_pane_key(
        _two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT, 60, 10, nest=True
    )
    assert message is not None
    assert "third panel" in message
    assert "ctrl+s" not in message
    wide = refuse_three_pane_key(
        _two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT, 200, 40, nest=True
    )
    assert wide is None
    turn_message = refuse_turn(nested, 60, 10)
    assert turn_message is not None
    assert "turn" in turn_message
    assert refuse_turn(nested, 200, 40) is None
    # Two-pane paths stay unguarded.
    assert (
        refuse_three_pane_key(
            _two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT, 60, 10, nest=False
        )
        is None
    )
    assert refuse_turn(_two_panes(Axis.ROWS, 0), 60, 10) is None


def test_fit_refusal_names_collapse_when_it_would_fit() -> None:
    message = refuse_three_pane_key(
        _two_panes(Axis.ROWS, 0),
        DeckLayout.LEFT_RIGHT,
        100,
        40,
        nest=True,
        collapsed_gain=38,
    )
    if message is not None:
        assert "ctrl+s" in message


def test_minimums_match_phase_contract() -> None:
    assert (MIN_DECK_PANEL_HEIGHT, MIN_DECK_PANEL_WIDTH) == (8, 40)


def test_choose_new_panel_picks_tools_for_main_and_files() -> None:
    picked = choose_new_panel(DeckId.MAIN, None, {DeckId.MAIN, DeckId.FILES}, {}, ())
    assert picked.deck is DeckId.TOOLS


def test_choose_new_panel_picks_final_on_positive_content() -> None:
    picked = choose_new_panel(
        DeckId.MAIN,
        None,
        {DeckId.MAIN, DeckId.FILES},
        {DeckId.TOOLS: False, DeckId.FINAL: True},
        (),
    )
    assert picked.deck is DeckId.FINAL


def test_three_panel_state_round_trips_with_pair() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    snapshot = snapshot_from_area_state(nested)
    assert len(snapshot.panels) == 3
    assert snapshot.pair_region in (0, 1)
    assert snapshot.pair_ratio in (30, 50, 70)
    # Pane IDs are reassigned in reading order on load, so the round trip
    # preserves geometry, reading-order decks, focus position and pair.
    rebuilt = area_state_from_snapshot(snapshot)
    assert geometry(rebuilt.grid) is geometry(nested.grid)
    assert [rebuilt.panels[pid].deck for pid in rebuilt.grid.panes] == [
        nested.panels[pid].deck for pid in nested.grid.panes
    ]
    assert list(rebuilt.grid.panes).index(rebuilt.grid.focused) == list(
        nested.grid.panes
    ).index(nested.grid.focused)
    assert rebuilt.grid.pair is not None
    assert rebuilt.grid.pair.region == nested.grid.pair.region
    assert rebuilt.grid.pair.ratio == nested.grid.pair.ratio


def test_v1_file_without_pair_loads_as_two_panels() -> None:
    decoded = json.loads(
        _serialize_agents_deck_state(
            AgentsDeckStateSnapshot(
                layout=DeckLayout.TOP_BOTTOM,
                panels=tuple(AgentsDeckStateSnapshot().panels),
            )
        )
    )
    assert "pair" not in decoded
    snapshot = _decode_agents_deck_state(decoded)
    assert len(snapshot.panels) <= 2


def test_old_reader_simulation_yields_valid_two_pane() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    snapshot = snapshot_from_area_state(nested)
    old_view = truncate_snapshot_to_two(snapshot)
    assert len(old_view.panels) == 2
    assert old_view.pair_region is None
    rebuilt = area_state_from_snapshot(old_view)
    assert geometry(rebuilt.grid) in (Geometry.R2, Geometry.C2)


def test_malformed_pair_recovers_to_two_panels() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    decoded = json.loads(_serialize_agents_deck_state(snapshot_from_area_state(nested)))
    decoded["pair"] = {"region": 5, "ratio": 99}
    snapshot = _decode_agents_deck_state(decoded)
    assert len(snapshot.panels) == 2
    assert snapshot.pair_region is None
    area_state_from_snapshot(snapshot)


def test_three_panels_without_pair_truncates() -> None:
    decoded = {
        "schema_version": 1,
        "layout": DeckLayout.TOP_BOTTOM.value,
        "ratio": 50,
        "focused": 2,
        "nodes_collapsed": False,
        "panels": [
            {"deck": DeckId.MAIN.value},
            {"deck": DeckId.FILES.value},
            {"deck": DeckId.TOOLS.value},
        ],
    }
    snapshot = _decode_agents_deck_state(decoded)
    assert len(snapshot.panels) == 2


def test_picker_hint_names_mru_target_with_glyph() -> None:
    nested = _nest(_two_panes(Axis.ROWS, 0), DeckLayout.LEFT_RIGHT)
    # Focus the main pane so the MRU other pane is the just-opened pair pane.
    state = dataclasses.replace(nested, grid=cycle_focus(nested.grid, -1))
    target = other_panel_target(state, state.grid.focused)
    hint = deck_picker_other_hint(target)
    assert target.glyph != ""
    assert target.glyph in hint
    assert target.label in hint


def test_zoom_chrome_names_three_of_three() -> None:
    from sase.ace.tui.widgets.decks.titles import ZoomChrome, deck_subtitle

    rendered = deck_subtitle(
        DeckId.MAIN,
        {},
        status=None,
        width=80,
        accent_for={},
        zoom=ZoomChrome(
            from_layout=DeckLayout.TOP_BOTTOM,
            panel_index=2,
            panel_count=3,
            zoom_key="Z",
            glyph="◲",
        ),
    )
    assert "◲ 3 of 3" in rendered.plain


def test_close_focused_is_inverse_of_nest() -> None:
    two = _two_panes(Axis.ROWS, 0)
    nested = toggle_split(
        two, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS), nest=True
    )
    undone = dataclasses.replace(
        nested, grid=close_focused(focus_pane(nested.grid, nested.grid.focused))
    )
    assert undone.grid.panes == two.grid.panes
    assert undone.grid.focused == two.grid.focused


def test_press_split_and_turn_helpers_cover_three_panes() -> None:
    grid = _nest(_two_panes(Axis.COLS, 1), DeckLayout.TOP_BOTTOM).grid
    assert geometry(grid) is Geometry.C3_MAIN_LEFT
    assert turn(turn(grid)) == grid
    assert press_split(grid, Axis.ROWS, grid.focused, nest=True) == turn(grid)


def test_three_panel_footer_replaces_focus_entry() -> None:
    from sase.ace.tui.models.agent import Agent, AgentType
    from sase.ace.tui.widgets import KeybindingFooter

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        response_path=None,
    )
    footer = KeybindingFooter()
    two_labels = [
        label for _, label in footer._compute_agent_bindings(agent, deck_split=True)
    ]
    assert "other panel" in two_labels
    three_labels = [
        label
        for _, label in footer._compute_agent_bindings(
            agent, deck_split=True, deck_three_panels=True
        )
    ]
    assert "other panel" not in three_labels
    assert "panel" in three_labels


async def test_nested_panels_keep_widget_identity() -> None:
    from pathlib import Path

    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.decks.area import DeckArea

    root = Path(__file__).resolve().parents[5]

    class _AreaApp(App[None]):
        CSS_PATH = root / "src/sase/ace/tui/styles.tcss"

        def compose(self) -> ComposeResult:
            yield DeckArea(id="agent-deck-area")

    app = _AreaApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        area = app.query_one("#agent-deck-area", DeckArea)
        widgets = (area.panel(0), area.panel(1), area.panel(2))
        two = toggle_split(
            DeckAreaState(), DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.FILES)
        )
        area.apply_state(two)
        await pilot.pause()
        assert len(area.visible_panels()) == 2
        three = toggle_split(
            two, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS), nest=True
        )
        area.apply_state(three)
        await pilot.pause()
        assert len(area.visible_panels()) == 3
        assert (area.panel(0), area.panel(1), area.panel(2)) == widgets
        closed = close_deck_panel(
            dataclasses.replace(three, grid=focus_pane(three.grid, three.grid.focused))
        )
        area.apply_state(closed)
        await pilot.pause()
        assert len(area.visible_panels()) == 2
        assert (area.panel(0), area.panel(1), area.panel(2)) == widgets
