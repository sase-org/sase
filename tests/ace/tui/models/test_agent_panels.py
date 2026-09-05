"""Tests for Agents-tab panel key selection."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    agents_for_panel,
    effective_tribe_per_agent,
    panel_key_per_agent,
)
from sase.core.time import local_now


def _agent(
    *,
    suffix: str | None,
    tribe: str | None = None,
    name: str = "agent",
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    start_time: datetime | None = datetime(2026, 4, 25, 12, 0, 0),
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=start_time,
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
    )


def test_all_tribe_assigned_agents_omit_no_tribe_panel() -> None:
    agents = [
        _agent(suffix="z", tribe="zulu"),
        _agent(suffix="a", tribe="alpha"),
        _agent(suffix="m", tribe="mike"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == ["alpha", "mike", "zulu"]
    assert group.focused_key == "alpha"


def test_mixed_agents_keep_no_tribe_panel_first() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="b", tribe="beta"),
        _agent(suffix="a", tribe="alpha"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == [None, "alpha", "beta"]
    assert group.focused_key is None


def test_implicit_and_explicit_default_share_reserved_panel() -> None:
    implicit = _agent(suffix="implicit", name="implicit")
    explicit = _agent(suffix="explicit", tribe="default", name="explicit")
    child = _agent(
        suffix="child",
        tribe="other",
        name="explicit.child",
        parent_timestamp="explicit",
        parent_workflow="explicit",
    )
    named = _agent(suffix="named", tribe="alpha", name="named")
    agents = [implicit, explicit, child, named]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == [None, "alpha"]
    assert panel_key_per_agent(agents) == [None, None, None, "alpha"]
    assert effective_tribe_per_agent(agents) == [
        "default",
        "default",
        "default",
        "alpha",
    ]
    assert agents_for_panel(agents, None) == [implicit, explicit, child]
    assert agents_for_panel(agents, "default") == [implicit, explicit, child]
    assert implicit.tribe is None
    assert explicit.tribe == "default"


def test_collapsed_middle_panel_moves_after_expanded_panels() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="a", tribe="alpha"),
        _agent(suffix="b", tribe="beta"),
        _agent(suffix="g", tribe="gamma"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={"beta"},
    )

    assert group.panel_keys == [None, "alpha", "gamma", "beta"]


def test_multiple_collapsed_panels_keep_canonical_order() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="g", tribe="gamma"),
        _agent(suffix="a", tribe="alpha"),
        _agent(suffix="b", tribe="beta"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={"gamma", "alpha"},
    )

    assert group.panel_keys == [None, "beta", "alpha", "gamma"]


def test_from_panel_keys_applies_same_collapsed_partition_and_focus_rules() -> None:
    group = AgentPanelGroup.from_panel_keys(
        [None, "alpha", "beta", "gamma"],
        focused_key="alpha",
        collapsed_panel_keys={"gamma", "alpha"},
    )

    assert group.panel_keys == [None, "beta", "alpha", "gamma"]
    assert group.focused_key == "alpha"
    assert group.focused_idx == 2


def test_collapsed_no_tribe_panel_moves_after_expanded_tribe_panels() -> None:
    agents = [
        _agent(suffix="u"),
        _agent(suffix="b", tribe="beta"),
        _agent(suffix="a", tribe="alpha"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        collapsed_panel_keys={None},
    )

    assert group.panel_keys == ["alpha", "beta", None]


def test_collapsed_last_partition_preserves_focused_panel_key() -> None:
    agents = [
        _agent(suffix="a", tribe="alpha"),
        _agent(suffix="b", tribe="beta"),
        _agent(suffix="g", tribe="gamma"),
    ]

    group = AgentPanelGroup.from_agents(
        agents,
        focused_key="beta",
        collapsed_panel_keys={"beta"},
    )

    assert group.panel_keys == ["alpha", "gamma", "beta"]
    assert group.focused_idx == 2
    assert group.focused_key == "beta"


def test_empty_agents_keep_no_tribe_fallback_panel() -> None:
    group = AgentPanelGroup.from_agents([])

    assert group.panel_keys == [None]
    assert group.focused_key is None


def test_starting_only_tribe_assigned_agents_do_not_create_tribe_panels() -> None:
    now = local_now()
    agents = [
        _agent(suffix="a", tribe="alpha", status="STARTING", start_time=now),
        _agent(suffix="b", tribe="beta", status="STARTING", start_time=now),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == []
    assert group.focused_key is None


def test_tribe_assigned_rendered_row_with_starting_row_shows_only_tribe_assigned_panel() -> (
    None
):
    agents = [
        _agent(suffix="a", tribe="alpha", status="STARTING", start_time=local_now()),
        _agent(suffix="b", tribe="beta", status="RUNNING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == ["beta"]
    assert group.focused_key == "beta"


def test_rendered_no_tribe_row_with_starting_row_shows_no_tribe_panel() -> None:
    agents = [
        _agent(suffix="a", tribe="alpha", status="STARTING", start_time=local_now()),
        _agent(suffix="b", status="RUNNING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == [None]
    assert group.focused_key is None


def test_starting_only_tribe_merged_mode_excludes_rows_from_default_panel() -> None:
    """Merged mode has a single ``@default`` panel, but STARTING rows stay out of it."""
    agents = [
        _agent(suffix="a", tribe="alpha", status="STARTING", start_time=local_now()),
        _agent(suffix="b", tribe="beta", status="STARTING", start_time=None),
    ]

    group = AgentPanelGroup.from_agents(agents, merge_tribe_panels=True)

    assert group.panel_keys == [None]
    assert agents_for_panel(agents, None, merge_tribe_panels=True) == []


def test_stale_and_missing_start_time_starting_rows_stay_hidden() -> None:
    """A STARTING row never earns a tribe panel, no matter its start_time age."""
    stale = datetime(2020, 1, 1, 0, 0, 0)
    agents = [
        _agent(suffix="a", tribe="alpha", status="STARTING", start_time=stale),
        _agent(suffix="b", tribe="beta", status="STARTING", start_time=None),
        _agent(suffix="c", tribe="gamma", status="RUNNING"),
    ]

    group = AgentPanelGroup.from_agents(agents)

    assert group.panel_keys == ["gamma"]
    assert group.focused_key == "gamma"


def test_workflow_child_inherits_parent_tribe_without_empty_no_tribe_panel() -> None:
    parent = _agent(suffix="parent", tribe="fix", name="parent")
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
        _agent(suffix="b", tribe="beta"),
        _agent(suffix="a", tribe="alpha"),
    ]

    group = AgentPanelGroup.from_agents(agents, focused_key=None)

    assert group.panel_keys == ["alpha", "beta"]
    assert group.focused_idx == 0
    assert group.focused_key == "alpha"


def test_merged_panels_use_one_panel_but_preserve_effective_tribes() -> None:
    parent = _agent(suffix="parent", tribe="fix", name="parent")
    child = _agent(
        suffix="child",
        name="child",
        parent_timestamp="parent",
        parent_workflow="wf",
    )
    review = _agent(suffix="review", tribe="review", name="review")
    agents = [parent, child, review]

    group = AgentPanelGroup.from_agents(
        agents,
        focused_key="review",
        merge_tribe_panels=True,
        collapsed_panel_keys={None, "fix"},
    )

    assert group.panel_keys == [None]
    assert group.focused_idx == 0
    assert panel_key_per_agent(agents, merge_tribe_panels=True) == [None, None, None]
    assert effective_tribe_per_agent(agents) == ["fix", "fix", "review"]


def test_clan_subtree_uses_outer_root_panel_in_split_and_merged_modes() -> None:
    phase = _agent(suffix="phase", tribe="epic", name="sase-6r.phase")
    phase.agent_clan = "sase-6r"
    phase.agent_clan_generation = "20260718080000"
    step = _agent(
        suffix="step",
        tribe="review",
        name="sase-6r.phase.step",
        parent_timestamp="phase",
        parent_workflow="phase",
    )
    peer = _agent(suffix="peer", tribe="review", name="sase-6r.peer")
    peer.agent_clan = "sase-6r"
    peer.agent_clan_generation = phase.agent_clan_generation
    clan = project_clan_tree([phase, step, peer])
    standalone = _agent(suffix="standalone", tribe="fix", name="standalone")
    standalone_step = _agent(
        suffix="standalone-step",
        name="standalone.step",
        parent_timestamp="standalone",
        parent_workflow="standalone",
    )
    unrelated = _agent(suffix="unrelated", tribe="review", name="unrelated")
    agents = [*clan, standalone, standalone_step, unrelated]

    expected_panel_keys = [None] * len(clan) + ["fix", "fix", "review"]
    expected_tribes = ["default"] * len(clan) + ["fix", "fix", "review"]
    assert clan[0].clan_tribes == ("epic", "review")
    assert effective_tribe_per_agent(agents) == expected_tribes
    assert panel_key_per_agent(agents) == expected_panel_keys
    assert AgentPanelGroup.from_agents(agents).panel_keys == [None, "fix", "review"]
    assert agents_for_panel(agents, None) == clan

    assert panel_key_per_agent(agents, merge_tribe_panels=True) == [None] * len(agents)
    assert agents_for_panel(agents, None, merge_tribe_panels=True) == agents


def test_new_clan_tribe_keeps_entire_subtree_in_one_panel() -> None:
    phase = _agent(suffix="20260718080001", tribe="legacy", name="research.phase")
    phase.agent_clan = "research"
    phase.agent_clan_generation = "20260718080000"
    phase.clan_tribe = "alpha"
    step = _agent(
        suffix="20260718080002",
        tribe="other-legacy",
        name="research.phase.step",
        parent_timestamp="20260718080001",
        parent_workflow="phase",
    )
    peer = _agent(
        suffix="20260718080003",
        tribe="ignored-legacy",
        name="research.peer",
    )
    peer.agent_clan = "research"
    peer.agent_clan_generation = phase.agent_clan_generation
    peer.clan_tribe = "quality"

    clan = project_clan_tree([phase, step, peer])

    assert clan[0].tribe == "quality"
    assert effective_tribe_per_agent(clan) == ["quality"] * len(clan)
    assert AgentPanelGroup.from_agents(clan).panel_keys == ["quality"]
    assert agents_for_panel(clan, "quality") == clan


def test_nested_monitor_inherits_clan_anchor_panel() -> None:
    family = _agent(suffix="family", tribe="epic", name="research.family")
    family.agent_clan = "research"
    family.agent_clan_generation = "20260817080000"
    family.agent_family = "research.family"
    family.agent_family_role = "root"
    starter = _agent(
        suffix="starter",
        name="research.family--2",
        parent_timestamp="family",
    )
    starter.agent_family = family.agent_family
    starter.agent_family_role = "code"
    monitor = _agent(
        suffix="monitor",
        tribe="review",
        name="research.family--mon-1",
        parent_timestamp="starter",
    )
    monitor.agent_family = family.agent_family
    monitor.agent_family_role = "monitor"
    standalone = _agent(suffix="standalone", tribe="fix", name="standalone")

    clan = project_clan_tree([family, starter, monitor])
    agents = [*clan, standalone]

    assert panel_key_per_agent(agents) == [None] * len(clan) + ["fix"]
    assert agents_for_panel(agents, None) == clan
    assert monitor in agents_for_panel(agents, None)


def test_panel_focus_next_skips_multiple_panels_and_wraps() -> None:
    group = AgentPanelGroup([None, "alpha", "beta", "gamma"])

    assert group.focus_next(skip={"alpha", "beta"}) is True
    assert group.focused_key == "gamma"
    assert group.focus_next(skip={"alpha", "beta"}) is True
    assert group.focused_key is None


def test_panel_focus_prev_skips_multiple_panels_and_wraps() -> None:
    group = AgentPanelGroup([None, "alpha", "beta", "gamma"])

    assert group.focus_prev(skip={"beta", "gamma"}) is True
    assert group.focused_key == "alpha"
    assert group.focus_prev(skip={"beta", "gamma"}) is True
    assert group.focused_key is None


def test_panel_focus_step_can_start_from_skipped_panel() -> None:
    group = AgentPanelGroup([None, "alpha", "beta"], focused_idx=1)

    assert group.focus_next(skip={"alpha"}) is True
    assert group.focused_key == "beta"


def test_panel_focus_step_returns_false_when_every_other_panel_is_skipped() -> None:
    group = AgentPanelGroup([None, "alpha", "beta"], focused_idx=1)

    assert group.focus_next(skip={None, "beta"}) is False
    assert group.focused_idx == 1
    assert group.focus_prev(skip={None, "beta"}) is False
    assert group.focused_idx == 1


def test_panel_focus_default_step_and_single_panel_behavior_are_unchanged() -> None:
    group = AgentPanelGroup([None, "alpha", "beta"])

    assert group.focus_next() is True
    assert group.focused_key == "alpha"
    assert group.focus_prev() is True
    assert group.focused_key is None
    assert group.focus_prev() is True
    assert group.focused_key == "beta"

    assert AgentPanelGroup([]).focus_next() is False
    assert AgentPanelGroup(["alpha"]).focus_prev() is False
