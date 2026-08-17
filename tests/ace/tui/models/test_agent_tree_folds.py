"""Fold state and query filtering across clan, family, and workflow rows."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import (
    agent_fold_key,
    filter_tree_rows,
    project_clan_tree,
)
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation

from ._agent_tree_helpers import _agent


def test_clan_and_members_fold_independently_through_recursive_ancestors() -> None:
    family = _agent("research.family", "family")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    workflow = _agent(
        "research.workflow",
        "workflow",
        agent_type=AgentType.WORKFLOW,
    )
    workflow_step = _agent(
        "prompt",
        "workflow-step",
        agent_type=AgentType.WORKFLOW,
        parent_timestamp=workflow.raw_suffix,
        parent_workflow="visual-workflow",
        step_type="agent",
        clan=None,
        generation=None,
    )
    hidden_step = _agent(
        "setup",
        "workflow-hidden",
        agent_type=AgentType.WORKFLOW,
        parent_timestamp=workflow.raw_suffix,
        parent_workflow="visual-workflow",
        step_type="bash",
        hidden=True,
        clan=None,
        generation=None,
    )
    projected = project_clan_tree(
        [family, family_member, workflow, workflow_step, hidden_step]
    )
    container = projected[0]
    fold_key = agent_fold_key(container)
    assert fold_key is not None
    family_key = agent_fold_key(family)
    workflow_key = agent_fold_key(workflow)
    assert family_key is not None
    assert workflow_key is not None
    manager = FoldStateManager()

    collapsed, counts = filter_agents_by_fold_state(projected, manager)
    assert collapsed == [container]
    assert counts == {
        fold_key: (2, 0),
        family_key: (1, 0),
        workflow_key: (1, 1),
    }
    assert _compute_fold_annotation(container, counts, set()) == " ×2"
    assert _compute_fold_annotation(family, counts, set()) == " ×1"
    assert _compute_fold_annotation(workflow, counts, set()) == " ×2"

    manager.expand(fold_key)
    expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert expanded == [container, family, workflow]
    assert _compute_fold_annotation(container, counts, {fold_key}) == ""

    manager.expand(workflow_key)
    member_expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert member_expanded == [container, family, workflow, workflow_step]
    assert family_member not in member_expanded
    assert _compute_fold_annotation(workflow, counts, {workflow_key}) == " ×2 −1"

    manager.expand(workflow_key)
    member_fully_expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert member_fully_expanded == [
        container,
        family,
        workflow,
        workflow_step,
        hidden_step,
    ]
    assert family_member not in member_fully_expanded
    assert (
        _compute_fold_annotation(
            workflow,
            counts,
            {workflow_key},
            {workflow_key},
        )
        == " ×2 +1"
    )

    manager.collapse(fold_key)
    masked, _ = filter_agents_by_fold_state(projected, manager)
    assert masked == [container]
    assert manager.get(workflow_key).name == "FULLY_EXPANDED"

    manager.expand(fold_key)
    reopened, _ = filter_agents_by_fold_state(projected, manager)
    assert reopened == member_fully_expanded


def test_clan_tree_query_retains_complete_immediate_parent_chain() -> None:
    family = _agent("research.family", "family")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    peer = _agent("research.peer", "peer")
    projected = project_clan_tree([family, family_member, peer])

    filtered = filter_tree_rows(
        projected,
        lambda row: row.raw_suffix == family_member.raw_suffix,
    )

    assert filtered == projected
