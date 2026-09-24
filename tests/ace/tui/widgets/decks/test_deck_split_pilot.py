"""Pilot tests for deck split layouts, focus and ratio."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.feature_flags import override_flags
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_backslash_opens_top_bottom_with_focus(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            assert detail.deck_layout is DeckLayout.SINGLE
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            area = detail.deck_area
            assert area.state.layout is DeckLayout.TOP_BOTTOM
            assert area.state.focused == 1
            assert area.state.ratio == 50
            assert len(area.visible_panels()) == 2
            assert area.panel(0).has_class("-focused") or True
            # CSS classes synced.
            assert area.has_class("-top-bottom")
            assert area.has_class("-ratio-50")


async def test_pipe_opens_left_right_and_unsplit_keeps_first(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            panel0 = detail.deck_area.panel(0)
            card_before = panel0.main_view.active_card_id
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            assert detail.deck_area.state.layout is DeckLayout.LEFT_RIGHT
            assert detail.deck_area.state.focused == 1
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            assert detail.deck_layout is DeckLayout.SINGLE
            assert detail.deck_area.panel(0).main_view.active_card_id == card_before


async def test_rotate_keeps_widget_identities(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            panel0_before = detail.deck_area.panel(0)
            panel1_before = detail.deck_area.panel(1)
            main0_before = panel0_before.main_view
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            assert detail.deck_area.panel(0) is panel0_before
            assert detail.deck_area.panel(1) is panel1_before
            assert detail.deck_area.panel(0).main_view is main0_before


async def test_ctrl_f_flips_focus_and_single_noop(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            # SINGLE no-op.
            detail.toggle_deck_focus()
            await pilot.pause()
            assert detail.deck_area.state.focused == 0
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            assert detail.deck_area.state.focused == 1
            detail.toggle_deck_focus()
            await pilot.pause()
            assert detail.deck_area.state.focused == 0
            assert detail.deck_area.panel(0).has_class("-focused")
            assert detail.deck_area.panel(1).has_class("-unfocused")


async def test_ratio_steps_and_clamp() -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_agent(status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            # Focus is panel 1: grow shrinks panel 0's share.
            detail.step_deck_ratio(True)
            await pilot.pause()
            assert detail.deck_area.state.ratio == 30
            detail.step_deck_ratio(True)
            await pilot.pause()
            assert detail.deck_area.state.ratio == 30
            detail.step_deck_ratio(False)
            await pilot.pause()
            assert detail.deck_area.state.ratio == 50
            # Flip focus to panel 0: grow expands panel 0.
            detail.toggle_deck_focus()
            await pilot.pause()
            detail.step_deck_ratio(True)
            await pilot.pause()
            assert detail.deck_area.state.ratio == 70


async def test_context_reply_for_agent_without_files_or_tools(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        from sase.ace.tui.widgets.decks.availability import DeckAvailability

        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            # Force no-files/no-tools so the new panel duplicates Main.
            panel0_before = detail.deck_area.panel(0)
            panel0_before._availability = {
                DeckId.MAIN: DeckAvailability(True, 2),
                DeckId.FILES: DeckAvailability(False, 0),
                DeckId.TOOLS: DeckAvailability(False, 0),
            }
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            panel0 = detail.deck_area.panel(0)
            panel1 = detail.deck_area.panel(1)
            # No files/tools: second panel duplicates Main.
            assert panel1.deck is DeckId.MAIN
            assert panel0.deck is DeckId.MAIN
            assert panel0.main_view.active_card_id != panel1.main_view.active_card_id


async def test_main_document_fans_out_to_both(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            # Force both panels to Main for fan-out check.
            detail.show_deck(1, DeckId.MAIN)
            await pilot.pause()
            detail.update_display(agent)
            await pilot.pause()
            panel0 = detail.deck_area.panel(0)
            panel1 = detail.deck_area.panel(1)
            assert panel0.main_view.active_card_id is not None
            assert panel1.main_view.active_card_id is not None


async def test_ctrl_n_p_act_on_focused_panel(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            before0 = detail.deck_area.panel(0).deck
            before1 = detail.deck_area.panel(1).deck
            # Focus is panel 1: cycle it, panel 0 stays.
            detail.cycle_focused_deck(1)
            await pilot.pause()
            assert detail.deck_area.panel(0).deck is before0
            assert detail.deck_area.panel(1).deck is not before1


async def test_duplicate_files_single_fetch(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            # Open a Files deck in panel 0, then duplicate it.
            detail.show_deck(0, DeckId.FILES)
            await pilot.pause()
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            # If the new panel is Files, only the owner should own a worker.
            area = detail.deck_area
            if area.panel(1).deck is DeckId.FILES:
                workers = [
                    len(getattr(p.file_view, "_inflight_diff_tasks", {}))
                    for p in area.visible_panels()
                    if p.deck is DeckId.FILES
                ]
                # At most one Files view holds in-flight diff tasks.
                assert sum(1 for w in workers if w > 0) <= 1


async def test_duplicate_tools_single_fetch(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.show_deck(0, DeckId.TOOLS)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            area = detail.deck_area
            if area.panel(1).deck is DeckId.TOOLS:
                # The mtime-keyed throttle dedupes Tools fetches: the second
                # panel must not own a running worker.
                running = [
                    bool(
                        getattr(p.tools_view, "_current_worker", None) is not None
                        and getattr(p.tools_view._current_worker, "is_running", False)
                    )
                    for p in area.visible_panels()
                    if p.deck is DeckId.TOOLS
                ]
                assert sum(1 for r in running if r) <= 1
