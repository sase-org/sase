"""Structural clan, family, and workflow fold transition tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_fold_transition_helpers import (
    StubFoldApp,
    make_agent,
    make_loader_shaped_aliased_plan_family,
    make_sequential_family,
    make_standalone_workflow_house,
)


def test_capital_h_collapses_family_then_clan_before_group_fold() -> None:
    projected, family, member = make_sequential_family(clan="research")
    clan = projected[0]
    app = StubFoldApp(projected, current_idx=projected.index(member))
    family_key = agent_fold_key(family)
    clan_key = agent_fold_key(clan)
    assert family_key is not None
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._fold_manager.expand(family_key)

    app.action_hooks_or_collapse_all()

    assert app.current_idx == projected.index(family)
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse_all()

    assert app.current_idx == projected.index(clan)
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse_all()

    assert app._current_group_key is not None
    assert app._group_fold_registry.snapshot()


def test_capital_h_collapses_aliased_plan_family_before_group_fold() -> None:
    agents, root, _main, coder, _steps = make_loader_shaped_aliased_plan_family()
    app = StubFoldApp(agents, current_idx=agents.index(coder))
    family_key = agent_fold_key(root)
    assert family_key is not None
    app._fold_manager.expand(family_key)

    app.action_hooks_or_collapse_all()

    assert app.current_idx == agents.index(root)
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._group_fold_registry.snapshot() == ()


@pytest.mark.parametrize("step_kind", ["agent", "bash", "python", "pre_prompt"])
def test_capital_h_collapses_workflow_step_owner_before_group(
    step_kind: str,
) -> None:
    agents, root, steps = make_standalone_workflow_house()
    selected = steps[step_kind]
    app = StubFoldApp(agents, current_idx=agents.index(selected))
    workflow_key = agent_fold_key(root)
    assert workflow_key is not None
    app._fold_manager.expand(workflow_key)

    app.action_hooks_or_collapse_all()

    assert app.current_idx == agents.index(root)
    assert app._fold_manager.get(workflow_key) is FoldLevel.COLLAPSED
    assert app._group_fold_registry.snapshot() == ()
    assert app.refilter_kwargs == [{"prior_pos": None, "refresh_content_index": False}]
    assert app._panel_selection_memory[None] == ("agent", agents.index(root))


def test_l_expands_child_owner_but_saturated_hidden_leaf_is_noop() -> None:
    agents, root, steps = make_standalone_workflow_house()
    workflow_key = agent_fold_key(root)
    assert workflow_key is not None
    app = StubFoldApp(agents, current_idx=agents.index(steps["bash"]))
    app._fold_manager.expand(workflow_key)

    app.action_expand_or_layout()

    assert app.current_idx == agents.index(steps["bash"])
    assert app._fold_manager.get(workflow_key) is FoldLevel.FULLY_EXPANDED
    assert app.refilter_calls == 1

    app.current_idx = agents.index(steps["pre_prompt"])
    app.action_expand_or_layout()

    assert app.current_idx == agents.index(steps["pre_prompt"])
    assert app._fold_manager.get(workflow_key) is FoldLevel.FULLY_EXPANDED
    assert app.refilter_calls == 1


def test_l_expands_running_parent_with_family_child() -> None:
    parent = make_agent(raw_suffix="parent-ts")
    child = make_agent(raw_suffix="child-ts")
    child.parent_timestamp = parent.raw_suffix
    app = StubFoldApp([parent, child], current_idx=0)

    app.action_expand_or_layout()

    assert app._fold_manager.get("parent-ts") is FoldLevel.EXPANDED
    assert app.refilter_calls == 1


def test_clan_l_is_a_binary_outer_fold_and_second_l_is_clamped() -> None:
    first = make_agent(raw_suffix="first")
    first.agent_clan = "research"
    first.agent_clan_generation = "generation"
    second = make_agent(raw_suffix="second")
    second.agent_clan = "research"
    second.agent_clan_generation = "generation"
    projected = project_clan_tree([first, second])
    app = StubFoldApp(projected)
    key = agent_fold_key(projected[0])
    assert key is not None

    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert app.refilter_calls == 2


def test_clan_member_l_l_and_child_member_capital_h_are_isolated() -> None:
    workflow = make_agent(raw_suffix="workflow", agent_type=AgentType.WORKFLOW)
    workflow.agent_clan = "research"
    workflow.agent_clan_generation = "generation"
    ordinary = make_agent(raw_suffix="ordinary", agent_type=AgentType.WORKFLOW)
    ordinary.parent_timestamp = workflow.raw_suffix
    ordinary.parent_workflow = "workflow"
    ordinary.step_type = "agent"
    hidden = make_agent(raw_suffix="hidden", agent_type=AgentType.WORKFLOW)
    hidden.parent_timestamp = workflow.raw_suffix
    hidden.parent_workflow = "workflow"
    hidden.step_type = "bash"
    hidden.is_hidden_step = True

    family = make_agent(raw_suffix="family")
    family.agent_clan = "research"
    family.agent_clan_generation = "generation"
    followup = make_agent(raw_suffix="followup")
    followup.parent_timestamp = family.raw_suffix

    projected = project_clan_tree([workflow, ordinary, hidden, family, followup])
    container, workflow, ordinary, hidden, family, followup = projected
    clan_key = agent_fold_key(container)
    workflow_key = agent_fold_key(workflow)
    family_key = agent_fold_key(family)
    assert clan_key is not None
    assert workflow_key is not None
    assert family_key is not None
    app = StubFoldApp(projected)

    app.action_expand_or_layout()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED

    app.current_idx = projected.index(workflow)
    app.action_expand_or_layout()
    assert app._fold_manager.get(workflow_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED

    app.action_expand_or_layout()
    assert app._fold_manager.get(workflow_key) is FoldLevel.FULLY_EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED

    app.current_idx = projected.index(hidden)
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(workflow_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(workflow)

    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(container)
    assert app._group_fold_registry.collapsed == set()


def test_collapsed_clan_masks_member_state_until_reopened() -> None:
    member = make_agent(raw_suffix="member", agent_type=AgentType.WORKFLOW)
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    child = make_agent(raw_suffix="child", agent_type=AgentType.WORKFLOW)
    child.parent_timestamp = member.raw_suffix
    child.parent_workflow = "workflow"
    child.step_type = "agent"
    projected = project_clan_tree([member, child])
    container, member, child = projected
    clan_key = agent_fold_key(container)
    member_key = agent_fold_key(member)
    assert clan_key is not None
    assert member_key is not None
    app = StubFoldApp(projected)

    app.action_expand_or_layout()
    app.current_idx = projected.index(member)
    app.action_expand_or_layout()
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED

    app.current_idx = projected.index(container)
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(member_key) is FoldLevel.COLLAPSED

    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(member_key) is FoldLevel.COLLAPSED

    app.action_expand_or_layout()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(member_key) is FoldLevel.COLLAPSED


def test_per_workflow_capital_h_runs_before_group_collapse() -> None:
    """Per-workflow ``H`` beats group collapse for an expanded workflow."""
    parent = make_agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = StubFoldApp([parent])
    app._fold_counts["ts1"] = (1, 0)
    app._fold_manager.expand("ts1")

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    assert app._group_fold_registry.collapsed == set()
