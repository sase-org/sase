"""Per-panel search overlay tests for deck-action-retarget."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.ace.tui.widgets.decks.search_corpus import deck_search_corpus
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_overlay_shows_on_focused_panel_only(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        area = detail.deck_area
        focused = area.focused_panel()
        other = area.panel(0 if focused.panel_index == 1 else 1)
        before_focused = focused.search_scroll()
        before_other = other.search_scroll()
        focused.show_search_overlay()
        await pilot.pause()
        assert before_focused.has_class("-shown")
        assert not before_other.has_class("-shown")
        # Showing never remounts: identities are stable.
        assert focused.search_scroll() is before_focused
        assert other.search_scroll() is before_other
        focused.hide_search_overlay()
        await pilot.pause()
        assert not focused.search_scroll().has_class("-shown")
        restored = focused.active_scroll().has_class("-shown") or focused.query_one(
            ".deck-empty-state"
        ).has_class("-shown")
        assert restored


async def test_main_corpus_joins_every_card(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(
            make_artifact_agent(
                tmp_path,
                status="DONE",
                raw_xprompt="searchable-context-marker",
            )
        )
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        panel.set_deck(DeckId.MAIN)
        await pilot.pause()
        corpus = deck_search_corpus(panel)
        assert corpus
        assert "searchable-context-marker" in corpus or "Context" in corpus


async def test_files_and_tools_corpus_paths(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        panel.set_deck(DeckId.FILES)
        await pilot.pause()
        assert isinstance(deck_search_corpus(panel), str)
        panel.set_deck(DeckId.TOOLS)
        await pilot.pause()
        assert isinstance(deck_search_corpus(panel), str)
