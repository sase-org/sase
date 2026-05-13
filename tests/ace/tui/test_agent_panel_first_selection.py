"""Regression tests for J/K panel switching selection on the Agents tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._display import AgentDisplayMixin
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
        self.artifact_viewer_guard_active = False
        self.notify = MagicMock()

    def _guard_agent_navigation_for_artifact_viewer(self) -> bool:
        if not self.artifact_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(self._agents)

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)


class _TrackingPanelWidget:
    def __init__(self, wid: str, *, highlighted: int | None = None) -> None:
        self.id = wid
        self.highlighted = highlighted
        self.update_highlight_calls: list[
            tuple[int, int | None, tuple[str, ...] | None]
        ] = []
        self.clear_highlight_calls = 0
        self.focus_calls = 0
        self._classes: set[str] = set()

    def update_highlight(
        self,
        current_idx: int,
        current_attempt_number: int | None = None,
        group_key: tuple[str, ...] | None = None,
    ) -> None:
        self.update_highlight_calls.append(
            (current_idx, current_attempt_number, group_key)
        )
        self.highlighted = current_idx

    def clear_highlight(self) -> None:
        self.clear_highlight_calls += 1
        self.highlighted = None

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        self.focus_calls += 1


class _QueryResults:
    def __init__(self, widgets: list[_TrackingPanelWidget]) -> None:
        self._widgets = widgets

    def results(self, _type: Any) -> list[_TrackingPanelWidget]:
        return self._widgets


class _OptimizedPanelSwitchApp(AgentPanelsMixin, PanelsMixin):
    """Harness for the optimized panel-switch refresh path."""

    _agents_visible_order = AgentsMixinCore._agents_visible_order
    _panel_navigation_stops = AgentsMixinCore._panel_navigation_stops
    _snap_current_idx_to_focused_panel = PanelsMixin._snap_current_idx_to_focused_panel
    _agent_panel_index = AgentDisplayMixin._agent_panel_index
    _panel_keys_per_agent = AgentDisplayMixin._panel_keys_per_agent

    def __init__(self, agents: list[Agent], *, focused_key: str | None) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 42
        self._agents = agents
        self._current_group_key: tuple[str, ...] | None = None
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents, focused_key)
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self.artifact_viewer_guard_active = False
        self._widgets = {
            "agent-list-panel": _TrackingPanelWidget("agent-list-panel", highlighted=0),
            "agent-list-panel-1": _TrackingPanelWidget(
                "agent-list-panel-1", highlighted=0
            ),
            "agent-list-panel-2": _TrackingPanelWidget(
                "agent-list-panel-2", highlighted=0
            ),
        }
        self.info_updates = 0
        self.detail_updates = 0
        self.debounced_detail_updates = 0

    def _guard_agent_navigation_for_artifact_viewer(self) -> bool:
        return self.artifact_viewer_guard_active

    def query_one(self, selector: str, _type: Any = None) -> Any:
        return self._widgets[selector.lstrip("#")]

    def query(self, _selector: str) -> _QueryResults:
        return _QueryResults(list(self._widgets.values()))

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_detail_immediate(self) -> None:
        self.detail_updates += 1

    def _fire_debounced_detail_update(self) -> None:
        self.debounced_detail_updates += 1


class _Debouncer:
    def __init__(self) -> None:
        self.scheduled = 0

    def schedule(self, _callback: Any) -> None:
        self.scheduled += 1


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
        project_file=f"/r/{project}/proj.sase",
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
    assert app.refresh_calls == [False]


def test_focus_next_agent_panel_guard_keeps_panel_and_selection() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="alpha", cl="a", name="tagged"),
    ]
    app = _StubApp(agents, focused_key=None)
    app.artifact_viewer_guard_active = True

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key is None
    assert app.current_idx == 0
    assert app._current_group_key == ("stale",)
    assert app.refresh_calls == []
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )


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


def test_optimized_panel_switch_clears_old_panel_highlight() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="alpha", cl="a", name="alpha-agent"),
        _agent(tag="beta", project="beta", cl="b", name="beta-agent"),
    ]
    app = _OptimizedPanelSwitchApp(agents, focused_key="alpha")
    app.current_idx = 1
    app._agent_detail_debouncer = _Debouncer()
    app._widgets["agent-list-panel-1"]._classes.add("-focused-panel")

    app.action_focus_next_agent_panel()

    old_widget = app._widgets["agent-list-panel-1"]
    new_widget = app._widgets["agent-list-panel-2"]
    assert app._panel_group.focused_key == "beta"
    assert app.current_idx == 2
    assert old_widget.highlighted is None
    assert old_widget.clear_highlight_calls == 1
    assert "-focused-panel" not in old_widget._classes
    assert new_widget.highlighted == 0
    assert new_widget.update_highlight_calls == [(0, None, None)]
    assert "-focused-panel" in new_widget._classes
    assert new_widget.focus_calls == 1


def test_refresh_panel_highlights_clears_every_nonfocused_panel() -> None:
    agents = [
        _agent(tag=None, project="home", cl="home", name="untagged"),
        _agent(tag="alpha", project="alpha", cl="a", name="alpha-agent"),
        _agent(tag="beta", project="beta", cl="b", name="beta-agent"),
    ]
    app = _OptimizedPanelSwitchApp(agents, focused_key="alpha")
    app.current_idx = 1
    app._widgets["agent-list-panel"]._classes.add("-focused-panel")
    app._widgets["agent-list-panel-2"]._classes.add("-focused-panel")

    app._refresh_panel_highlights_impl()

    focused_widget = app._widgets["agent-list-panel-1"]
    stale_main = app._widgets["agent-list-panel"]
    stale_beta = app._widgets["agent-list-panel-2"]
    assert focused_widget.highlighted == 0
    assert focused_widget.update_highlight_calls == [(0, 42, None)]
    assert "-focused-panel" in focused_widget._classes
    assert stale_main.highlighted is None
    assert stale_beta.highlighted is None
    assert stale_main.clear_highlight_calls == 1
    assert stale_beta.clear_highlight_calls == 1
    assert "-focused-panel" not in stale_main._classes
    assert "-focused-panel" not in stale_beta._classes
