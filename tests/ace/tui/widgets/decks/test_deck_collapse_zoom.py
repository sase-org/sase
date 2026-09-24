"""Node-panel collapse and in-place zoom for deck panels."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks import layout as deck_layout
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)
from sase.ace.tui.widgets.decks.node_spine import (
    NodeSpine,
    _spine_geometry,
)
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _split_state() -> DeckAreaState:
    """Return a LEFT_RIGHT state with distinct decks and focus right."""
    opened = deck_layout.toggle_split(
        DeckAreaState(), DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.FILES)
    )
    assert opened.layout is DeckLayout.LEFT_RIGHT
    assert opened.focused == 1
    return opened


def test_toggle_nodes_collapsed_round_trips_and_preserves_layout() -> None:
    state = _split_state()
    collapsed = deck_layout.toggle_nodes_collapsed(state)
    assert collapsed.nodes_collapsed is True
    assert collapsed.layout is state.layout
    assert collapsed.panels == state.panels
    assert collapsed.focused == state.focused
    assert collapsed.ratio == state.ratio
    assert deck_layout.toggle_nodes_collapsed(collapsed) == state


def test_zoom_round_trip_restores_snapshot_exactly() -> None:
    state = _split_state()
    zoomed = deck_layout.toggle_zoom(state)
    assert deck_layout.is_zoomed(zoomed)
    assert zoomed.layout is DeckLayout.SINGLE
    assert zoomed.focused == 1
    assert zoomed.nodes_collapsed is True
    # The zoomed panel keeps its deck, card preference and scroll owner:
    # both panel entries survive, only the layout changes.
    assert zoomed.panels == state.panels
    assert deck_layout.toggle_zoom(zoomed) == state
    assert deck_layout.toggle_zoom(zoomed) == state
    assert deck_layout.toggle_zoom(state) == zoomed


def test_zoom_from_single_keeps_panel_and_collapses() -> None:
    zoomed = deck_layout.toggle_zoom(DeckAreaState())
    assert zoomed.focused == 0
    assert zoomed.panels == DeckAreaState().panels
    assert zoomed.nodes_collapsed is True
    assert deck_layout.toggle_zoom(zoomed) == DeckAreaState()


def test_layout_key_ends_zoom_without_restoring() -> None:
    zoomed = deck_layout.toggle_zoom(_split_state())
    ended = deck_layout.toggle_split(
        zoomed, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.TOOLS)
    )
    assert not deck_layout.is_zoomed(ended)
    # Applies to the zoomed (single, focused) state: a fresh split opens.
    assert ended.layout is DeckLayout.TOP_BOTTOM
    assert ended.focused == 1
    assert ended.panels[0].deck is DeckId.FILES


def test_collapse_key_ends_zoom_then_toggles() -> None:
    zoomed = deck_layout.toggle_zoom(_split_state())
    assert zoomed.nodes_collapsed is True
    ended = deck_layout.toggle_nodes_collapsed(zoomed)
    assert not deck_layout.is_zoomed(ended)
    assert ended.nodes_collapsed is False
    assert ended.layout is DeckLayout.SINGLE


def test_node_spine_expand_requested_handler_name() -> None:
    assert NodeSpine.ExpandRequested.handler_name == "on_node_spine_expand_requested"


def test_spine_geometry_edges() -> None:
    assert _spine_geometry(0, 0, 5) == (0, 0)
    assert _spine_geometry(10, 0, 0) == (0, 0)
    start, size = _spine_geometry(10, 0, 5)
    assert (start, size) == (0, 2)
    end_start, end_size = _spine_geometry(10, 4, 5)
    assert end_start + end_size <= 10
    assert end_start > start
    single_start, single_size = _spine_geometry(7, 0, 1)
    assert (single_start, single_size) == (0, 7)


def _check(action: str, tab: str) -> bool | None:
    from sase.ace.tui._app_action_availability import check_app_action

    class _App:
        current_tab = tab
        _prompt_input_active = lambda self: False  # noqa: E731
        _screen_stack: tuple[object, ...] = ()

        def __getattr__(self, _name: str) -> object:
            return None

    app = _App()
    return check_app_action(app, action, (), lambda _a, _p: None)


def test_collapse_and_zoom_gating() -> None:
    assert _check("toggle_node_panel", "agents") is None
    assert _check("toggle_node_panel", "artifacts") is False
    assert _check("toggle_node_panel", "services") is False
    # Z is the in-place zoom.
    assert _check("zoom_panel", "agents") is None
    assert _check("zoom_panel", "artifacts") is False


def test_keymap_default_and_catalog_cover_collapse() -> None:
    from sase.ace.tui.commands import build_command_catalog, get_command_by_id
    from sase.ace.tui.keymaps import load_keymap_registry

    registry = load_keymap_registry({})
    assert registry.app.toggle_node_panel == "ctrl+s"
    catalog = build_command_catalog(registry)
    assert get_command_by_id(catalog, "app.toggle_node_panel") is not None


def test_info_chip_renders_collapse_and_zoom() -> None:
    from unittest.mock import patch

    from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
    from tests.ace.tui.widgets._agent_info_panel_helpers import (
        collect_text,
        stable_state_kwargs,
    )

    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(position=12, total=47))  # type: ignore[arg-type]
    assert "nodes" not in collect_text(panel)
    with patch.object(panel, "update"):
        panel.update_state(
            **stable_state_kwargs(position=12, total=47, nodes_collapsed=True)
        )  # type: ignore[arg-type]
    collapsed_text = collect_text(panel)
    assert "nodes 12/47" in collapsed_text
    assert "zoom" not in collapsed_text
    with patch.object(panel, "update"):
        panel.update_state(
            **stable_state_kwargs(
                position=12, total=47, nodes_collapsed=True, nodes_zoomed=True
            )
        )  # type: ignore[arg-type]
    zoomed_text = collect_text(panel)
    assert "zoom" in zoomed_text
    assert "nodes 12/47" in zoomed_text


async def test_collapse_expand_in_single_and_split(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        assert detail.is_nodes_collapsed is False
        detail.toggle_node_panel()
        await pilot.pause()
        assert detail.is_nodes_collapsed is True
        assert detail.deck_area.state.nodes_collapsed is True
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_area.state.layout is DeckLayout.LEFT_RIGHT
        assert detail.is_nodes_collapsed is True
        detail.toggle_node_panel()
        await pilot.pause()
        assert detail.is_nodes_collapsed is False


async def test_zoom_round_trip_keeps_widget_and_card(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        area = detail.deck_area
        widget_before = area.focused_panel()
        deck_before = widget_before.deck
        card_before = widget_before.main_view.active_card_id
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed is True
        assert detail.is_nodes_collapsed is True
        assert area.visible_panels() == (widget_before,)
        assert area.focused_panel() is widget_before
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed is False
        assert area.state.layout is DeckLayout.LEFT_RIGHT
        assert area.focused_panel() is widget_before
        assert widget_before.deck is deck_before
        assert widget_before.main_view.active_card_id == card_before


async def test_split_key_ends_zoom(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed is True
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        assert detail.is_deck_zoomed is False
        assert detail.deck_area.state.layout is DeckLayout.TOP_BOTTOM


async def test_collapse_key_ends_zoom(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed is True
        detail.toggle_node_panel()
        await pilot.pause()
        assert detail.is_deck_zoomed is False


async def test_spine_tracks_selection() -> None:
    from textual.app import App as _App
    from textual.app import ComposeResult as _ComposeResult

    class _SpineApp(_App[None]):
        def compose(self) -> _ComposeResult:
            yield NodeSpine(id="agent-node-spine")

    app = _SpineApp()
    async with app.run_test(size=(10, 12)):
        spine = app.query_one("#agent-node-spine", NodeSpine)
        spine.update_position(3, 47)
        assert spine.position == (3, 47)
        spine.update_position(0, 0)
        assert spine.position == (0, 0)
