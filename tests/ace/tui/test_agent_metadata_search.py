"""Pilot coverage for inline Vim search in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
import pytest
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui._agents_zoom_panel_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


async def _set_prompt_text(page: AcePage, content: str) -> AgentPromptPanel:
    await page.wait_for(lambda _state: not page.app._agent_detail_debouncer.is_pending)
    panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
    panel.update(Text(content))
    await page.pause()
    return panel


def _search_agents() -> list[Agent]:
    stopped = datetime(2026, 7, 19, 10, 10, 0)
    return [
        _make_agent(
            cl_name="search-fixture-first",
            agent_name="search.fixture.first",
            status="DONE",
            stop_time=stopped,
        ),
        _make_agent(
            cl_name="search-fixture-second",
            agent_name="search.fixture.second",
            status="DONE",
            stop_time=stopped,
            raw_suffix="20260612-120100",
        ),
    ]


async def test_inline_metadata_search_commit_repeat_q_and_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 2)
        await _set_prompt_text(
            page,
            "Alpha needle result\nSecond needle result\n"
            + "\n".join(f"filler line {index}" for index in range(80)),
        )

        await page.press("slash", "n", "e", "e", "d", "l", "e")
        await page.pause()

        command = page.app.query_one("#agent-search-command", Static)
        search_scroll = page.app.query_one(
            "#agent-search-scroll",
            VerticalScroll,
        )
        assert page.app._agent_metadata_search.mode == "typing"
        assert page.app._agent_metadata_search.current_selection is not None
        assert "[1/2]" in command.render().plain
        assert "Ctrl+R" in command.border_subtitle
        assert not search_scroll.has_class("hidden")
        assert page.app.query_one("#agent-prompt-scroll").has_class("hidden")

        frozen_corpus = page.app._agent_metadata_search.corpus
        await page.press("ctrl+r")
        await page.pause()
        assert page.app._agent_metadata_search.direction == "reverse"
        assert page.app._agent_metadata_search.query == "needle"
        assert page.app._agent_metadata_search.corpus == frozen_corpus
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("ctrl+r")
        await page.pause()
        assert page.app._agent_metadata_search.direction == "forward"
        assert page.app._agent_metadata_search.query == "needle"
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 0

        await page.press("enter", "n")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "committed"
        assert page.app._agent_metadata_search.last_search == ("needle", "forward")
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("N")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "committed"
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 0

        await page.press("ctrl+r", "n")
        await page.pause()
        assert page.app._agent_metadata_search.last_search == ("needle", "reverse")
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("ctrl+f")
        await page.pause()
        assert int(search_scroll.scroll_y) > 0

        await page.press("q")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "off"
        assert search_scroll.has_class("hidden")
        assert not page.app.query_one("#agent-prompt-scroll").has_class("hidden")

        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        assert page.app._agent_metadata_search.mode == "off"
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("slash", "n", "e", "e", "d", "l", "e", "enter")
        selected_before = page.app._get_selected_agent()
        await page.press("j")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "off"
        assert page.app._get_selected_agent() is not selected_before


async def test_inline_metadata_search_yank_and_frozen_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda text: copied.append(text) or True,
    )
    patch_startup_loaders(monkeypatch, agents=_search_agents()[:1])

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        prompt = await _set_prompt_text(
            page,
            "Alpha needle result\nSecond needle result\n",
        )
        await page.press("slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.pause()

        frozen = page.app._agent_metadata_search.corpus
        prompt.update(Text("replacement content from background refresh"))
        await page.pause()
        overlay = page.app.query_one("#agent-search-panel", Static)
        assert "needle" in (renderable_to_text(overlay.content) or "")
        assert page.app._agent_metadata_search.corpus == frozen

        screen_type = type(page.app.screen)
        monkeypatch.setattr(
            screen_type,
            "get_selected_text",
            lambda _screen: "mouse-selected text",
        )
        await page.press("y")
        monkeypatch.setattr(
            screen_type,
            "get_selected_text",
            lambda _screen: "",
        )
        await page.press("y", "Y")
        await page.pause()
        assert copied == [
            "mouse-selected text",
            "needle",
            "Alpha needle result",
        ]


async def test_inline_metadata_search_exits_when_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents()[:1])

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await _set_prompt_text(page, "Alpha needle result\n")
        await page.press("slash", "n")
        assert page.app._agent_metadata_search.is_active

        detail = page.app.query_one("#agent-detail-panel")
        detail.show_empty()
        await page.pause()

        assert not page.app._agent_metadata_search.is_active
        assert page.app.query_one("#agent-search-scroll").has_class("hidden")


def test_metadata_search_actions_are_agents_only() -> None:
    agents = AceApp(auto_start_axe=False, initial_tab="agents")
    changespecs = AceApp(auto_start_axe=False, initial_tab="changespecs")
    axe = AceApp(auto_start_axe=False, initial_tab="axe")

    assert agents.check_action("search_forward", ()) is not False
    assert agents.check_action("search_reverse", ()) is False
    agents._agent_metadata_search.mode = "typing"
    assert agents.check_action("search_reverse", ()) is not False
    agents._agent_metadata_search.mode = "off"

    for action in ("search_forward", "search_reverse"):
        assert changespecs.check_action(action, ()) is False
        assert axe.check_action(action, ()) is False


async def test_inline_metadata_search_reverse_key_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"keymaps": {"app": {"search_reverse": "f5"}}}},
    ):
        async with AcePage(
            query='"search-fixture"',
            initial_tab="agents",
        ) as page:
            await wait_for_startup(page)
            await _set_prompt_text(
                page,
                "Alpha needle result\nSecond needle result\n",
            )

            await page.press("slash", "n", "e", "e", "d", "l", "e")
            await page.pause()
            assert page.app._agent_metadata_search.direction == "forward"
            assert page.app._agent_metadata_search.current_selection is not None
            assert page.app._agent_metadata_search.current_selection.index == 0

            await page.press("ctrl+r")
            await page.pause()
            assert page.app._agent_metadata_search.direction == "forward"
            assert page.app._agent_metadata_search.query == "needle"

            await page.press("f5")
            await page.pause()
            command = page.app.query_one("#agent-search-command", Static)
            assert page.app._agent_metadata_search.direction == "reverse"
            assert page.app._agent_metadata_search.current_selection is not None
            assert page.app._agent_metadata_search.current_selection.index == 1
            assert "f5" in command.border_subtitle
