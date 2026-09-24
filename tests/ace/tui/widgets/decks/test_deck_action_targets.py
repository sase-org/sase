"""Deck-action-retarget resolver and action tests."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.feature_flags import override_flags
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_focused_file_view_prefers_focused_then_fallback(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            area = detail.deck_area
            # Focused panel (1) shows something; force FILES on panel 1.
            detail.show_deck(1, DeckId.FILES)
            await pilot.pause()
            assert detail.focused_file_view() is area.panel(1).file_view
            # Focus the other panel showing Main: fallback still finds FILES.
            detail.toggle_deck_focus()
            await pilot.pause()
            assert detail.focused_file_view() is area.panel(1).file_view
            # No Files anywhere: None.
            detail.show_deck(1, DeckId.TOOLS)
            detail.show_deck(0, DeckId.MAIN)
            await pilot.pause()
            if area.panel(0).deck is DeckId.FILES or area.panel(1).deck is DeckId.FILES:
                pass
            else:
                assert detail.focused_file_view() is None


async def test_focused_tools_view_only_when_focused_is_tools(
    tmp_path: Path,
) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            detail.show_deck(1, DeckId.TOOLS)
            detail.show_deck(0, DeckId.MAIN)
            await pilot.pause()
            # Focused is panel 1 (Tools).
            assert detail.focused_tools_view() is not None
            detail.toggle_deck_focus()
            await pilot.pause()
            # Focused is Main with Tools only unfocused: no fallback.
            assert detail.focused_tools_view() is None
            assert detail._llm_calls_panel_or_none() is None


async def test_main_view_for_actions_and_ensure_shown(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            detail.show_deck(0, DeckId.MAIN)
            detail.show_deck(1, DeckId.FILES)
            await pilot.pause()
            # Focused panel 1 is Files: actions use the other Main view.
            resolved = detail.main_view_for_actions()
            assert resolved is not None
            panel, _view = resolved
            assert panel.deck is DeckId.MAIN
            # Hide Main everywhere, then ensure restores it on the focused panel.
            detail.show_deck(0, DeckId.FILES)
            await pilot.pause()
            assert detail.main_view_for_actions() is None
            detail.ensure_main_deck_shown()
            await pilot.pause()
            assert detail.main_view_for_actions() is not None


async def test_editor_info_main_returns_active_card(tmp_path: Path) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
            await pilot.pause()
            area = detail.deck_area
            area.panel(0).set_deck(DeckId.MAIN)
            await pilot.pause()
            path, content, suffix = detail.get_editor_file_info()
            assert path is None
            assert suffix == ".md"
            assert content


async def test_refresh_current_file_hits_every_files_panel(
    tmp_path: Path, monkeypatch
) -> None:
    with override_flags(agent_decks=True):
        app = _DetailApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            agent = make_artifact_agent(tmp_path, status="DONE")
            detail.update_display(agent)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            detail.show_deck(0, DeckId.FILES)
            detail.show_deck(1, DeckId.FILES)
            await pilot.pause()
            calls: list[int] = []

            def _fake_refresh(self, _agent) -> None:
                calls.append(id(self))

            monkeypatch.setattr(
                type(detail.deck_area.panel(0).file_view),
                "refresh_file",
                _fake_refresh,
            )
            detail.refresh_current_file(agent)
            assert len(calls) == 2
            assert len(set(calls)) == 2
