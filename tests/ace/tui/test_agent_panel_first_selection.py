"""Regression tests for J/K panel switching selection on the Agents tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._display_panels import PanelsMixin
from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent


class _StubApp(AgentPanelsMixin):
    """Small harness for panel switching with production render-order helpers."""

    _agents_visible_order = AgentsMixinCore._agents_visible_order
    _panel_navigation_stops = AgentsMixinCore._panel_navigation_stops
    _snap_current_idx_to_focused_panel = PanelsMixin._snap_current_idx_to_focused_panel

    def __init__(self, agents: list[Agent], *, focused_key: str | None) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 42
        self._agents = agents
        self._current_group_key: tuple[str, ...] | None = ("stale",)
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._panel_group = AgentPanelGroup.from_agents(agents, focused_key)
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self.refresh_calls: list[bool] = []

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(self._agents)

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)


def _agent(
    *,
    tag: str | None,
    project: str,
    cl: str,
    name: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=name,
    )


def test_focus_next_agent_panel_selects_first_rendered_agent_not_first_raw() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="zeta", cl="z", name="raw-first"),
        _agent(tag="alpha", project="alpha", cl="a", name="render-first"),
        _agent(tag="alpha", project="beta", cl="b", name="render-second"),
        _agent(tag="beta", project="omega", cl="o", name="other-panel"),
    ]
    app = _StubApp(agents, focused_key=None)

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 2
    assert app._agents[app.current_idx].agent_name == "render-first"
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_calls == [True]


def test_focus_prev_agent_panel_selects_last_rendered_agent_not_last_raw() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="zeta", cl="z", name="raw-first"),
        _agent(tag="alpha", project="alpha", cl="a", name="render-first"),
        _agent(tag="alpha", project="beta", cl="b", name="render-second"),
        _agent(tag="beta", project="omega", cl="o", name="other-panel"),
    ]
    app = _StubApp(agents, focused_key="beta")
    app.current_idx = 4

    app.action_focus_prev_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 1
    assert app._agents[app.current_idx].agent_name == "raw-first"
    assert app._current_group_key is None
    assert app.current_attempt_number is None


def test_panel_switch_can_land_on_first_collapsed_banner() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="zeta", cl="z", name="raw-first"),
        _agent(tag="alpha", project="alpha", cl="a", name="banner-agent"),
        _agent(tag="alpha", project="beta", cl="b", name="render-second"),
    ]
    app = _StubApp(agents, focused_key=None)
    app._group_fold_registry.collapse(("alpha",))

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app._current_group_key == ("alpha",)
    assert app.current_idx == 2
    assert app._agents[app.current_idx].agent_name == "banner-agent"
    assert app.current_attempt_number is None


def test_prev_panel_switch_can_land_on_last_collapsed_banner() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="zeta", cl="z", name="banner-agent"),
        _agent(tag="alpha", project="alpha", cl="a", name="render-first"),
        _agent(tag="alpha", project="beta", cl="b", name="render-second"),
        _agent(tag="beta", project="omega", cl="o", name="other-panel"),
    ]
    app = _StubApp(agents, focused_key="beta")
    app.current_idx = 4
    app._group_fold_registry.collapse(("zeta",))

    app.action_focus_prev_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app._current_group_key == ("zeta",)
    assert app.current_idx == 1
    assert app._agents[app.current_idx].agent_name == "banner-agent"
    assert app.current_attempt_number is None
