"""Mounted header-panel behavior for the Agents tab sticky identity header."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import find_identity_header
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot

from sase.ace.tui.models._agent_tree import project_clan_tree


def _solo() -> Any:
    return make_agent(agent_name="solo")


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_agent(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display_immediate(agent)
    await pilot.pause()


def _header_panel(detail: AgentDetail) -> AgentHeaderPanel:
    return detail.query_one("#agent-header-panel", AgentHeaderPanel)


def _header_text(panel: AgentHeaderPanel) -> str:
    content = panel.query_one("#agent-header-content")
    return renderable_to_text(getattr(content, "content", None)) or ""


async def test_header_collapsed_by_default_with_title_and_hint() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_identity
        assert not panel.is_expanded
        assert detail.header_toggle_available() is True
        assert panel.border_title is not None
        assert "AGENT SHELL" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert "d" in str(panel.border_subtitle)
        rows = _header_text(panel).splitlines()
        assert len(rows) == 2


async def test_toggle_expands_to_full_fields_and_back() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)

        assert detail.toggle_header_expanded() is True
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)
        assert "Name:" in _header_text(panel)

        assert detail.toggle_header_expanded() is False
        assert not panel.is_expanded
        assert "more" in str(panel.border_subtitle)
        assert len(_header_text(panel).splitlines()) == 2


async def test_body_excludes_identity_lines() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        body = renderable_to_text(prompt.content) or ""
        assert "AGENT SHELL" not in body
        combined = renderable_to_text(prompt.inline_document_renderable()) or ""
        assert "AGENT SHELL" in combined
        assert "Name:" in combined


async def test_expanded_state_persists_across_selection_and_tribe() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.toggle_header_expanded() is True

        await _show_agent(detail, make_agent(agent_name="other"), pilot)
        panel = _header_panel(detail)
        assert panel.is_expanded
        assert "Name:" in _header_text(panel)

        detail.show_tribe_summary(make_tribe_snapshot())
        await pilot.pause()
        assert panel.is_expanded
        assert "TRIBE" in str(panel.border_title)


async def test_clan_selection_shows_header() -> None:
    member = make_clan_agent(
        "clan-test", status="RUNNING", start=datetime(2024, 1, 1), stop=None
    )
    container = project_clan_tree([member])[0]
    assert container.is_clan_container
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.header_toggle_available() is True

        await _show_agent(detail, container, pilot)
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_identity
        assert detail.header_toggle_available() is True
        assert "CLAN" in str(panel.border_title)
        assert not panel.is_expanded
        assert len(_header_text(panel).splitlines()) == 2

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "Name:" in _header_text(panel)
        assert "Status:" in _header_text(panel)

        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        assert len(_header_text(panel).splitlines()) == 2

        await _show_agent(detail, _solo(), pilot)
        assert not panel.is_expanded
        assert detail.toggle_header_expanded() is True
        await _show_agent(detail, container, pilot)
        assert panel.is_expanded
        assert "Name:" in _header_text(panel)


async def test_secondary_only_keeps_header_visible_and_toggleable() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)

        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "Name:" in _header_text(panel)
        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True


async def test_search_overlay_keeps_header_visible() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.show_deck(0, DeckId.TOOLS)
        await pilot.pause()
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True
        detail.show_deck(0, DeckId.MAIN)
        await pilot.pause()
        assert not panel.has_class("hidden")


async def test_hint_document_forces_expansion() -> None:
    agent = _solo()
    document, _ = build_header_text(agent, cheap=True, detach_identity=True)
    assert isinstance(document, AgentHeaderRenderable)
    identity = find_identity_header(document)
    assert identity is not None
    hinted = dataclasses.replace(identity, has_hints=True)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, agent, pilot)
        panel = _header_panel(detail)
        assert not panel.is_expanded
        panel.show_identity(hinted)
        assert "Name:" in _header_text(panel)


async def test_bottom_pinned_body_stays_pinned_across_toggle() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        detail.toggle_header_expanded()
        await pilot.pause()
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_empty_state_hides_header() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.header_toggle_available() is True
        detail.show_empty()
        await pilot.pause()
        panel = _header_panel(detail)
        assert panel.has_class("hidden")
        assert detail.header_toggle_available() is False


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


class _FakeAgentsApp:
    current_tab = "agents"
    _screen_stack = ("screen",)

    def __init__(self, *, prompt_active: bool, detail: Any) -> None:
        self._prompt_active = prompt_active
        self._detail = detail

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def query_one(self, _selector: str, _type: Any = None) -> Any:
        return self._detail


class _FakeDetail:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    def header_toggle_available(self) -> bool:
        return self._available


def test_toggle_unavailable_while_prompt_input_owns_keys() -> None:
    available = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=True))
    assert check_app_action(available, "toggle_agent_header", (), _fallback) is True
    busy = _FakeAgentsApp(prompt_active=True, detail=_FakeDetail(available=True))
    assert check_app_action(busy, "toggle_agent_header", (), _fallback) is False
    hidden = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=False))
    assert check_app_action(hidden, "toggle_agent_header", (), _fallback) is False
