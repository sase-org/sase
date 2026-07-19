"""Tests for resolving the focused Agents-tab group banner."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sase.ace.tui.actions.agents._group_focus import get_focused_agent_group
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "shared-change",
        "project_file": "/tmp/projects/proj_a/proj_a.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 7, 13, 10, 0, 0),
        "raw_suffix": "20260713100000",
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _two_panel_agents() -> list[Agent]:
    return [
        _make_agent(raw_suffix="20260713100100", tribe="epic"),
        _make_agent(raw_suffix="20260713100200"),
        _make_agent(raw_suffix="20260713100300", tribe="epic"),
        _make_agent(raw_suffix="20260713100400"),
    ]


def test_focused_group_is_panel_scoped_and_remapped_to_global_indices() -> None:
    agents = _two_panel_agents()
    owner = SimpleNamespace(
        _agents=agents,
        _panel_group=AgentPanelGroup.from_agents(agents, focused_key=None),
        _grouping_mode=GroupingMode.STANDARD,
        _current_group_key=("proj_a",),
    )

    group = get_focused_agent_group(owner)

    assert group is not None
    assert group.agent_indices == (1, 3)


def test_focused_group_uses_selected_tribe_panel() -> None:
    agents = _two_panel_agents()
    owner = SimpleNamespace(
        _agents=agents,
        _panel_group=AgentPanelGroup.from_agents(agents, focused_key="epic"),
        _grouping_mode=GroupingMode.STANDARD,
        _current_group_key=("proj_a",),
    )

    group = get_focused_agent_group(owner)

    assert group is not None
    assert group.agent_indices == (0, 2)


def test_focused_group_merged_panels_includes_all_rendered_agents() -> None:
    agents = _two_panel_agents()
    owner = SimpleNamespace(
        _agents=agents,
        _panel_group=AgentPanelGroup.from_agents(agents, merge_tribe_panels=True),
        _agent_panels_grouped=True,
        _grouping_mode=GroupingMode.STANDARD,
        _current_group_key=("proj_a",),
    )

    group = get_focused_agent_group(owner)

    assert group is not None
    assert group.agent_indices == (0, 1, 2, 3)


def test_focused_group_stale_key_returns_none() -> None:
    agents = _two_panel_agents()
    owner = SimpleNamespace(
        _agents=agents,
        _panel_group=AgentPanelGroup.from_agents(agents),
        _grouping_mode=GroupingMode.STANDARD,
        _current_group_key=("missing",),
    )

    assert get_focused_agent_group(owner) is None


def test_focused_group_without_panel_group_uses_rendered_full_list() -> None:
    first = _make_agent(raw_suffix="20260713100100", tribe="epic")
    hidden_starting = _make_agent(raw_suffix="20260713100200", status="STARTING")
    last = _make_agent(raw_suffix="20260713100300")
    owner = SimpleNamespace(
        _agents=[first, hidden_starting, last],
        _grouping_mode=GroupingMode.STANDARD,
        _current_group_key=("proj_a",),
    )

    group = get_focused_agent_group(owner)

    assert group is not None
    assert group.agent_indices == (0, 2)
