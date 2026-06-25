"""Tests for Agents-tab onboarding visibility."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._display_detail import DetailMixin
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)


def _mounted_onboarding_plain(page: AcePage) -> str:
    onboarding = page.query_one_widget("#agent-onboarding-panel")
    return "\n".join(
        getattr(child.render(), "plain", "") for child in onboarding.query(Static)
    )


class _PredicateApp(DetailMixin):
    def __init__(
        self,
        *,
        loaded: bool,
        query: str = "",
        agents_with_children: list[object] | None = None,
    ) -> None:
        self._agents_first_load_done = loaded
        self._agent_search_query = query
        self._agents_with_children = agents_with_children or []


def test_agents_onboarding_predicate_requires_loaded_empty_no_query() -> None:
    app = _PredicateApp(loaded=True)

    assert app._should_show_agents_onboarding() is True


def test_agents_onboarding_predicate_hides_before_first_load() -> None:
    app = _PredicateApp(loaded=False)

    assert app._should_show_agents_onboarding() is False


def test_agents_onboarding_predicate_hides_when_agents_exist() -> None:
    app = _PredicateApp(loaded=True, agents_with_children=[object()])

    assert app._should_show_agents_onboarding() is False


def test_agents_onboarding_predicate_hides_for_active_query() -> None:
    app = _PredicateApp(loaded=True, query="status:failed")

    assert app._should_show_agents_onboarding() is False


async def test_agents_onboarding_visible_after_empty_load_tab_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)

        onboarding = page.query_one_widget("#agent-onboarding-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert not onboarding.has_class("hidden")
        assert detail.has_class("hidden")
        assert "Welcome to sase ace" in _mounted_onboarding_plain(page)


async def test_agents_onboarding_hidden_when_agents_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        onboarding = page.query_one_widget("#agent-onboarding-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert onboarding.has_class("hidden")
        assert not detail.has_class("hidden")


async def test_agents_onboarding_hides_after_first_agent_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        assert "Welcome to sase ace" in _mounted_onboarding_plain(page)

        page.app._agents_with_children = [agents()[0]]
        page.app._refilter_agents()
        await page.expect_state("agent_count", 1)

        onboarding = page.query_one_widget("#agent-onboarding-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert onboarding.has_class("hidden")
        assert not detail.has_class("hidden")
