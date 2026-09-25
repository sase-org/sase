"""Pilot tests for showing a deck in the other panel (picker capital letters)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _mounted_detail(app: _DetailApp, pilot, tmp_path: Path) -> AgentDetail:
    await pilot.pause()
    detail = app.query_one("#agent-detail-panel", AgentDetail)
    detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
    await pilot.pause()
    return detail


async def _open_split(
    detail: AgentDetail, pilot, layout: DeckLayout, decks: tuple[DeckId, DeckId]
) -> None:
    """Open ``layout`` with ``decks`` in panels 0 and 1 (focus lands on 1)."""
    detail.toggle_deck_split(layout)
    await pilot.pause()
    detail.show_deck(0, decks[0])
    detail.show_deck(1, decks[1])
    await pilot.pause()


async def test_single_opens_bottom_panel_and_keeps_focus(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        assert detail.deck_layout is DeckLayout.SINGLE

        assert detail.show_deck_in_other_panel(None, DeckId.FILES) is True
        await pilot.pause()

        area = detail.deck_area
        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.panels[0].deck is DeckId.MAIN
        assert area.state.panels[1].deck is DeckId.FILES
        assert area.panel(1).deck is DeckId.FILES
        assert area.state.focused == 0
        assert area.panel(0).has_class("-focused")
        assert area.panel(1).has_class("-unfocused")
        assert area.has_class("-top-bottom")


async def test_top_bottom_focus_bottom_shows_deck_in_top(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        await _open_split(
            detail, pilot, DeckLayout.TOP_BOTTOM, (DeckId.MAIN, DeckId.FILES)
        )
        area = detail.deck_area
        assert area.state.focused == 1

        assert detail.show_deck_in_other_panel(None, DeckId.TOOLS) is True
        await pilot.pause()

        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.panels[0].deck is DeckId.TOOLS
        assert area.state.panels[1].deck is DeckId.FILES
        assert area.panel(0).deck is DeckId.TOOLS
        assert area.state.focused == 1


async def test_left_right_focus_right_shows_deck_in_left_and_keeps_layout(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        await _open_split(
            detail, pilot, DeckLayout.LEFT_RIGHT, (DeckId.MAIN, DeckId.FILES)
        )
        area = detail.deck_area
        assert area.state.focused == 1

        assert detail.show_deck_in_other_panel(None, DeckId.TOOLS) is True
        await pilot.pause()

        assert area.state.layout is DeckLayout.LEFT_RIGHT
        assert area.has_class("-left-right")
        assert area.state.panels[0].deck is DeckId.TOOLS
        assert area.state.panels[1].deck is DeckId.FILES
        assert area.state.focused == 1


async def test_explicit_source_panel_targets_its_opposite(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        await _open_split(
            detail, pilot, DeckLayout.TOP_BOTTOM, (DeckId.MAIN, DeckId.FILES)
        )
        area = detail.deck_area
        assert area.state.focused == 1

        # The picker was opened from panel 0 even though focus moved on.
        assert detail.show_deck_in_other_panel(0, DeckId.TOOLS) is True
        await pilot.pause()

        assert area.state.panels[0].deck is DeckId.MAIN
        assert area.state.panels[1].deck is DeckId.TOOLS


async def test_other_panel_already_showing_deck_is_a_noop(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        assert detail.show_deck_in_other_panel(None, DeckId.FILES) is True
        await pilot.pause()
        before = detail.deck_area.state

        assert detail.show_deck_in_other_panel(None, DeckId.FILES) is False
        await pilot.pause()

        assert detail.deck_area.state == before


async def test_duplicate_main_from_single_prefers_the_next_card(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        area = detail.deck_area
        active = area.panel(0).main_view.active_card_id
        assert active is not None

        assert detail.show_deck_in_other_panel(None, DeckId.MAIN) is True
        await pilot.pause()

        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.focused == 0
        assert area.state.panels[0].deck is DeckId.MAIN
        assert area.state.panels[1].deck is DeckId.MAIN
        preferred = area.state.panels[1].preferred_card
        assert preferred is not None and preferred != active
        assert area.panel(1).main_view.active_card_id == preferred
        assert area.panel(0).main_view.active_card_id == active


async def test_zoomed_from_single_ends_zoom_and_opens_bottom_panel(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        area = detail.deck_area
        before_collapsed = area.state.nodes_collapsed
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed
        assert area.state.nodes_collapsed is True

        assert detail.show_deck_in_other_panel(None, DeckId.FILES) is True
        await pilot.pause()

        assert not detail.is_deck_zoomed
        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.nodes_collapsed is before_collapsed
        assert area.state.focused == 0
        assert area.state.panels[1].deck is DeckId.FILES


async def test_zoomed_from_left_right_restores_layout_and_fills_other_panel(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        await _open_split(
            detail, pilot, DeckLayout.LEFT_RIGHT, (DeckId.MAIN, DeckId.FILES)
        )
        area = detail.deck_area
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed
        assert area.state.focused == 1

        assert detail.show_deck_in_other_panel(None, DeckId.TOOLS) is True
        await pilot.pause()

        assert not detail.is_deck_zoomed
        assert area.state.layout is DeckLayout.LEFT_RIGHT
        assert area.state.panels[0].deck is DeckId.TOOLS
        assert area.state.panels[1].deck is DeckId.FILES
        assert area.state.focused == 1
        assert not area.panel(0).has_class("hidden")

        # Zoom again: the other panel already shows the deck, but the zoom
        # still ends, so the call still reports a change.
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert detail.is_deck_zoomed
        assert detail.show_deck_in_other_panel(None, DeckId.TOOLS) is True
        await pilot.pause()
        assert not detail.is_deck_zoomed
        assert area.state.layout is DeckLayout.LEFT_RIGHT
        assert area.state.panels[0].deck is DeckId.TOOLS


async def test_deck_changed_while_zoomed_survives_the_capital_pick(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)
        await _open_split(
            detail, pilot, DeckLayout.TOP_BOTTOM, (DeckId.MAIN, DeckId.FILES)
        )
        area = detail.deck_area
        detail.toggle_deck_zoom()
        await pilot.pause()
        # Ctrl+N while zoomed changes the zoomed (focused) panel's deck.
        detail.cycle_focused_deck(1)
        await pilot.pause()
        assert area.state.panels[1].deck is DeckId.TOOLS

        assert detail.show_deck_in_other_panel(None, DeckId.FILES) is True
        await pilot.pause()

        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.panels[0].deck is DeckId.FILES
        assert area.state.panels[1].deck is DeckId.TOOLS


async def test_toggle_deck_split_still_focuses_the_new_panel(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = await _mounted_detail(app, pilot, tmp_path)

        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()

        area = detail.deck_area
        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.focused == 1
        assert area.panel(1).has_class("-focused")
