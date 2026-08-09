"""Tests for Agents-tab onboarding visibility."""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _onboarding_launch_targets, _onboarding_plugins
from sase.ace.tui.actions.agents._display_detail import DetailMixin
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    patches,
    patch_startup_loaders,
    wait_for_startup,
)


def _mounted_onboarding_plain(page: AcePage) -> str:
    onboarding = page.query_one_widget("#agent-quickstart-panel")
    return "\n".join(
        getattr(child.render(), "plain", "") for child in onboarding.query(Static)
    )


def _assert_agents_onboarding_layout(page: AcePage, *, active: bool) -> None:
    agents_view = page.query_one_widget("#agents-view")
    list_container = page.query_one_widget("#agent-list-container")
    info_panel = page.query_one_widget("#agent-info-panel")
    expected_chrome_display = not active

    assert agents_view.has_class("-onboarding-active") is active
    assert list_container.display is expected_chrome_display
    assert info_panel.display is expected_chrome_display


async def _wait_for_onboarding_launch_target_refresh(
    page: AcePage,
    calls: list[bool],
) -> None:
    await page.wait_for(
        lambda _state: (
            bool(calls)
            and not page.app._agents_onboarding_launch_targets_refresh_scheduled
            and not page.app._agents_onboarding_launch_targets_refresh_running
        )
    )
    await page.pause()


async def _wait_for_onboarding_plugins_refresh(
    page: AcePage,
    calls: list[bool],
) -> None:
    await page.wait_for(
        lambda _state: (
            bool(calls)
            and not page.app._agents_onboarding_plugins_refresh_scheduled
            and not page.app._agents_onboarding_plugins_refresh_running
        )
    )
    await page.pause()


def _onboarding_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visible-agent",
        project_file="/workspace/sase/visible_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 30, 6, 0, 0),
        raw_suffix="20260630-060000-visible",
        agent_name="visible",
    )


def _hidden_only_workflow_agents() -> list[Agent]:
    parent_suffix = "20260630-060000-hidden-workflow"
    project_file = "/workspace/sase/hidden_project.sase"
    return [
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="hidden-only",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 6, 30, 6, 0, 0),
            stop_time=datetime(2026, 6, 30, 6, 0, 1),
            raw_suffix=parent_suffix,
            workflow="hidden_only",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="hidden-only",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 6, 30, 6, 0, 0),
            stop_time=datetime(2026, 6, 30, 6, 0, 1),
            raw_suffix=f"{parent_suffix}-0",
            parent_workflow="hidden_only",
            parent_timestamp=parent_suffix,
            step_name="internal setup",
            step_type="bash",
            step_index=0,
            total_steps=1,
            is_hidden_step=True,
        ),
    ]


class _PredicateApp(DetailMixin):
    def __init__(
        self,
        *,
        loaded: bool,
        query: str = "",
        visible_agents: list[Agent] | None = None,
        agents_with_children: list[Agent] | None = None,
    ) -> None:
        self._agents_first_load_done = loaded
        self._agent_search_query = query
        self._agents = visible_agents or []
        self._agents_with_children = agents_with_children or []


def test_agents_onboarding_predicate_requires_loaded_empty_no_query() -> None:
    app = _PredicateApp(loaded=True)

    assert app._should_show_agents_onboarding() is True


def test_agents_onboarding_predicate_hides_before_first_load() -> None:
    app = _PredicateApp(loaded=False)

    assert app._should_show_agents_onboarding() is False


def test_agents_onboarding_predicate_hides_when_agents_exist() -> None:
    app = _PredicateApp(loaded=True, visible_agents=[_onboarding_agent()])

    assert app._should_show_agents_onboarding() is False


def test_agents_onboarding_predicate_uses_visible_agents() -> None:
    app = _PredicateApp(
        loaded=True,
        visible_agents=[],
        agents_with_children=[_onboarding_agent()],
    )

    assert app._should_show_agents_onboarding() is True


def test_agents_onboarding_predicate_hides_for_active_query() -> None:
    app = _PredicateApp(loaded=True, query="status:failed")

    assert app._should_show_agents_onboarding() is False


async def test_agents_onboarding_visible_after_empty_load_tab_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert not onboarding.has_class("hidden")
        assert detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=True)
        assert "Every agent you launch" in _mounted_onboarding_plain(page)


async def test_agents_onboarding_visible_after_empty_load_direct_agents_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert not onboarding.has_class("hidden")
        assert detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=True)
        assert "Every agent you launch" in _mounted_onboarding_plain(page)


async def test_agents_onboarding_launch_target_refresh_stores_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def _has_launch_targets() -> bool:
        calls.append(True)
        return True

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_launch_targets,
        "discover_agents_onboarding_launch_targets_available",
        _has_launch_targets,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_launch_target_refresh(page, calls)

        plain = _mounted_onboarding_plain(page)
        assert page.app._agents_onboarding_launch_targets_available is True
        assert "Every agent you launch" in plain
        assert "pick a project or PR first." not in plain


async def test_agents_onboarding_launch_target_refresh_stores_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def _has_launch_targets() -> bool:
        calls.append(True)
        return False

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_launch_targets,
        "discover_agents_onboarding_launch_targets_available",
        _has_launch_targets,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_launch_target_refresh(page, calls)

        plain = _mounted_onboarding_plain(page)
        assert page.app._agents_onboarding_launch_targets_available is False
        assert "Every agent you launch" in plain
        assert "Launch your first agent" in plain
        assert "pick a project or PR first." not in plain


async def test_agents_onboarding_plugin_refresh_stores_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def _no_plugins_installed() -> bool:
        calls.append(True)
        return False

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_plugins,
        "discover_agents_onboarding_plugins_installed",
        _no_plugins_installed,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_plugins_refresh(page, calls)

        plain = _mounted_onboarding_plain(page)
        assert page.app._agents_onboarding_plugins_installed is False
        assert "SASE Admin Center" in plain
        assert "sase-github" not in plain


async def test_agents_onboarding_plugin_refresh_stores_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def _plugins_installed() -> bool:
        calls.append(True)
        return True

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_plugins,
        "discover_agents_onboarding_plugins_installed",
        _plugins_installed,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_plugins_refresh(page, calls)

        plain = _mounted_onboarding_plain(page)
        assert page.app._agents_onboarding_plugins_installed is True
        assert "SASE Admin Center" in plain
        assert "sase-github" not in plain


async def test_agents_onboarding_visible_for_hidden_only_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_hidden_only_workflow_agents())

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        assert len(page.app._agents_with_children) == 2

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert not onboarding.has_class("hidden")
        assert detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=True)
        assert "Every agent you launch" in _mounted_onboarding_plain(page)


async def test_agents_onboarding_hidden_when_agents_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert onboarding.has_class("hidden")
        assert not detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=False)


async def test_agents_onboarding_reappears_after_last_visible_agent_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        page.app._agents_with_children = []
        page.app._refilter_agents()
        await page.expect_state("agent_count", 0)

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert not onboarding.has_class("hidden")
        assert detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=True)
        assert "Every agent you launch" in _mounted_onboarding_plain(page)


async def test_agents_onboarding_hides_after_first_agent_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        assert "Every agent you launch" in _mounted_onboarding_plain(page)

        page.app._agents_with_children = [agents()[0]]
        page.app._refilter_agents()
        await page.expect_state("agent_count", 1)

        onboarding = page.query_one_widget("#agent-quickstart-panel")
        detail = page.query_one_widget("#agent-detail-panel")
        assert onboarding.has_class("hidden")
        assert not detail.has_class("hidden")
        _assert_agents_onboarding_layout(page, active=False)
