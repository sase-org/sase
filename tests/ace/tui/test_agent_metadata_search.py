"""Pilot coverage for inline Vim search in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import AcePage, set_agent_prompt_document
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.agents_filter_bar import AgentsFilterBar
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui._agents_zoom_panel_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


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
        await set_agent_prompt_document(
            page,
            "Alpha needle result\nSecond needle result\n"
            + "\n".join(f"filler line {index}" for index in range(80)),
        )

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e")
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

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        assert page.app._agent_metadata_search.mode == "off"
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
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
        await set_agent_prompt_document(
            page,
            "Alpha needle result\nSecond needle result\n",
        )
        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.pause()

        frozen = page.app._agent_metadata_search.corpus
        await set_agent_prompt_document(
            page,
            "replacement content from background refresh",
        )
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


async def test_pinned_metadata_document_survives_a_debounced_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued detail repaint must not replace the pinned corpus.

    Before the document was pinned this is exactly what dropped the
    injected corpus under load, after which ``/`` captured the real agent
    document and the search legitimately found nothing.
    """
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 2)
        panel = await set_agent_prompt_document(page, "Alpha needle result\n")

        page.app._agent_detail_debouncer.schedule(
            page.app._fire_debounced_detail_update
        )
        await page.wait_for(
            lambda _state: not page.app._agent_detail_debouncer.is_pending,
        )
        await page.pause()

        assert "needle" in (renderable_to_text(panel.content) or "")


async def test_inline_metadata_search_exits_when_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents()[:1])

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await set_agent_prompt_document(page, "Alpha needle result\n")
        await page.press("comma", "slash", "n")
        assert page.app._agent_metadata_search.is_active

        detail = page.app.query_one("#agent-detail-panel")
        detail.show_empty()
        await page.pause()

        assert not page.app._agent_metadata_search.is_active
        assert page.app.query_one("#agent-search-scroll").has_class("hidden")


def test_metadata_search_start_is_a_leader_action() -> None:
    agents = AceApp(auto_start_axe=False, initial_tab="agents")

    assert not hasattr(agents._keymap_registry.app, "search_forward")
    assert "edit_query" not in agents._keymap_registry.leader_mode.keys
    assert agents._keymap_registry.leader_mode.keys["search_forward"] == "slash"
    assert agents._keymap_registry.app.search_reverse == "ctrl+r"


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
            await set_agent_prompt_document(
                page,
                "Alpha needle result\nSecond needle result\n",
            )

            await page.press("comma", "slash", "n", "e", "e", "d", "l", "e")
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


async def test_bare_slash_opens_agents_query_editor_not_metadata_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.press("slash")
        await page.pause()

        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is True
        assert page.app._agents_filter_session_open is True
        assert not page.app._agent_metadata_search.is_active


async def test_leader_metadata_search_does_not_modify_committed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        page.app._agent_search_query = "cl:search-fixture-first"
        page.app._refilter_agents()
        await page.pause()
        committed = page.app._agent_search_query

        await set_agent_prompt_document(page, "Alpha needle result\n")
        await page.press("comma", "slash", "n")
        await page.pause()

        assert page.app._agent_metadata_search.is_active
        assert page.app._agent_search_query == committed
