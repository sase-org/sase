"""Tests for Agents-tab panel key selection."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    effective_tag_per_agent,
    panel_key_per_agent,
)


def _agent(
    *,
    suffix: str | None,
    tag: str | None = None,
    name: str = "agent",
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
    )


def test_all_tagged_agents_omit_untagged_panel() -> None:
    agents = [
        _agent(suffix="z", tag="zulu"),
        _agent(suffix="a", tag="alpha"),
        _agent(suffix="m", tag="mike"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == ["alpha", "mike", "zulu"]
    assert group.focused_key == "alpha"


def test_mixed_agents_keep_untagged_panel_first() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="b", tag="beta"),
        _agent(suffix="a", tag="alpha"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == [None, "alpha", "beta"]
    assert group.focused_key is None


def test_collapsed_middle_panel_moves_after_expanded_panels() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="a", tag="alpha"),
        _agent(suffix="b", tag="beta"),
        _agent(suffix="g", tag="gamma"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={"beta"},
    )

    assert group.panel_keys == [None, "alpha", "gamma", "beta"]


def test_multiple_collapsed_panels_keep_canonical_order() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="g", tag="gamma"),
        _agent(suffix="a", tag="alpha"),
        _agent(suffix="b", tag="beta"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={"gamma", "alpha"},
    )

    assert group.panel_keys == [None, "beta", "alpha", "gamma"]


def test_collapsed_untagged_panel_moves_after_expanded_tag_panels() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="b", tag="beta"),
        _agent(suffix="a", tag="alpha"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={None},
    )

    assert group.panel_keys == ["alpha", "beta", None]


def test_collapsed_last_partition_preserves_focused_panel_key() -> None:
    agents = [
        _agent(suffix="a", tag="alpha"),
        _agent(suffix="b", tag="beta"),
        _agent(suffix="g", tag="gamma"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        focused_key="beta",
        collapsed_panel_keys={"beta"},
    )

    assert group.panel_keys == ["alpha", "gamma", "beta"]
    assert group.focused_idx == 2
    assert group.focused_key == "beta"


def test_empty_agents_keep_untagged_fallback_panel() -> None:
    group = AgentPanelGroup.from_agents([])

    assert group.panel_keys == [None]
    assert group.focused_key is None


def test_starting_only_tagged_agents_do_not_create_tag_panels() -> None:
    agents = [
        _agent(suffix="a", tag="alpha", status="STARTING"),
        _agent(suffix="b", tag="beta", status="STARTING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == []
    assert group.focused_key is None


def test_tagged_rendered_row_with_starting_row_shows_only_tagged_panel() -> None:
    agents = [
        _agent(suffix="a", tag="alpha", status="STARTING"),
        _agent(suffix="b", tag="beta", status="RUNNING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == ["beta"]
    assert group.focused_key == "beta"


def test_rendered_untagged_row_with_starting_row_shows_untagged_panel() -> None:
    agents = [
        _agent(suffix="a", tag="alpha", status="STARTING"),
        _agent(suffix="b", status="RUNNING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == [None]
    assert group.focused_key is None


def test_workflow_child_inherits_parent_tag_without_empty_untagged_panel() -> None:
    parent = _agent(suffix="parent", tag="fix", name="parent")
    child = _agent(
        suffix="child",
        name="child",
        parent_timestamp="parent",
        parent_workflow="wf",
    )

    agents = [parent, child]
    group = AgentPanelGroup.from_agents(agents)

    assert panel_key_per_agent(agents) == ["fix", "fix"]
    assert group.panel_keys == ["fix"]
    assert group.focused_key == "fix"


def test_missing_focused_key_falls_back_to_first_available_panel() -> None:
    agents = [
        _agent(suffix="b", tag="beta"),
        _agent(suffix="a", tag="alpha"),
    ]

    group = AgentPanelGroup.from_agents(agents, focused_key=None)

    assert group.panel_keys == ["alpha", "beta"]
    assert group.focused_idx == 0
    assert group.focused_key == "alpha"


def test_merged_panels_use_one_panel_but_preserve_effective_tags() -> None:
    parent = _agent(suffix="parent", tag="fix", name="parent")
    child = _agent(
        suffix="child",
        name="child",
        parent_timestamp="parent",
        parent_workflow="wf",
    )
    review = _agent(suffix="review", tag="review", name="review")
    agents = [parent, child, review]

    group = AgentPanelGroup.from_agents(
        agents,
        focused_key="review",
        merge_tag_panels=True,
        collapsed_panel_keys={None, "fix"},
    )

    assert group.panel_keys == [None]
    assert group.focused_idx == 0
    assert panel_key_per_agent(agents, merge_tag_panels=True) == [None, None, None]
    assert effective_tag_per_agent(agents) == ["fix", "fix", "review"]
