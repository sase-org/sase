"""Agents-tab projection and fold behavior for rootless clans."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import (
    agent_fold_key,
    agent_parent_fold_key,
    filter_tree_rows,
    presentation_anchor,
    presentation_anchor_lookup,
    project_clan_tree,
    tree_parent,
    tree_parent_lookup,
)
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation

_GENERATION = "20260717100000"


def _agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    step_type: str | None = None,
    hidden: bool = False,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
    tag: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/sase.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        run_start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type=step_type,
        is_hidden_step=hidden,
        agent_clan=clan,
        agent_clan_generation=generation,
        tag=tag,
    )


def test_project_clan_tree_inserts_container_and_three_depths() -> None:
    family = _agent("research.family", "family", tag="epic")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
        tag="review",
    )
    solo = _agent("research.solo", "solo", status="DONE", tag="review")

    projected = project_clan_tree([family, family_member, solo])

    container = projected[0]
    assert container.is_clan_container is True
    assert container.display_name == "research"
    assert container.agent_clan_generation == _GENERATION
    assert container.clan_tags == ("epic", "review")
    assert container.runtime_children == [family, solo]
    assert projected == [container, family, family_member, solo]
    assert [row.tree_depth for row in projected] == [0, 1, 2, 1]
    clan_key = agent_fold_key(container)
    assert family.tree_parent_key == clan_key
    assert solo.tree_parent_key == clan_key
    assert family_member.tree_parent_key == family.raw_suffix
    assert agent_fold_key(family) == family.raw_suffix
    assert agent_parent_fold_key(family) == clan_key
    assert agent_parent_fold_key(family_member) == family.raw_suffix

    lookup = tree_parent_lookup(projected)
    assert tree_parent(family_member, lookup) is family
    assert tree_parent(family, lookup) is container
    anchors = presentation_anchor_lookup(projected, lookup)
    assert [anchors[id(row)] for row in projected] == [container] * 4


def test_presentation_anchor_handles_orphans_and_cycles_deterministically() -> None:
    orphan = _agent("orphan", "orphan", clan=None, generation=None)
    orphan.tree_parent_key = "missing"
    orphan.tree_depth = 2
    shallow = _agent("cycle.shallow", "shallow", clan=None, generation=None)
    deep = _agent("cycle.deep", "deep", clan=None, generation=None)
    shallow.tree_parent_key = deep.raw_suffix
    shallow.tree_depth = 1
    deep.tree_parent_key = shallow.raw_suffix
    deep.tree_depth = 2
    rows = [deep, orphan, shallow]

    parent_lookup = tree_parent_lookup(rows)
    anchors = presentation_anchor_lookup(rows, parent_lookup)

    assert anchors[id(orphan)] is orphan
    assert anchors[id(shallow)] is shallow
    assert anchors[id(deep)] is shallow
    assert presentation_anchor(orphan, parent_lookup) is orphan
    assert presentation_anchor(shallow, parent_lookup) is shallow
    assert presentation_anchor(deep, parent_lookup) is shallow


def test_project_clan_tree_keeps_generations_separate() -> None:
    old = _agent("research.old", "old", generation="old")
    new = _agent("research.new", "new", generation="new")

    projected = project_clan_tree([new, old])

    containers = [row for row in projected if row.is_clan_container]
    assert [row.agent_clan_generation for row in containers] == ["new", "old"]
    assert containers[0].runtime_children == [new]
    assert containers[1].runtime_children == [old]
    assert new.tree_parent_key == agent_fold_key(containers[0])
    assert old.tree_parent_key == agent_fold_key(containers[1])


def test_clan_tree_does_not_invent_a_changespec_banner_from_one_member() -> None:
    one = _agent("first-changespec", "one")
    two = _agent("second-changespec", "two")
    projected = project_clan_tree([one, two])

    group_keys = [
        entry.group.group_key
        for entry in build_agent_tree(projected)
        if entry.group is not None
    ]

    assert group_keys == [("tmp",)]


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


def test_clan_and_member_rows_render_glyph_tags_and_depth_guides() -> None:
    family = _agent("research.family", "family", tag="epic")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    container, family, family_member = project_clan_tree([family, family_member])

    container_text, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        fold_annotation=" ×2",
        now=datetime(2026, 7, 17, 10, 5, 0),
    )
    family_text, _, _ = format_agent_option(
        family,
        1,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 5, 0),
    )
    member_text, _, _ = format_agent_option(
        family_member,
        2,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 5, 0),
    )

    assert container_text.plain.startswith("⌂ research @epic (RUNNING) ×2 [R1]")
    assert family_text.plain.startswith("  └─ research.family")
    assert family_member.tree_depth == 2
    assert member_text.plain.startswith("  │  └─ research.family--code")


def test_clan_row_renders_unread_count_in_both_fold_states() -> None:
    done = _agent("research.done", "done", status="DONE")
    failed = _agent("research.failed", "failed", status="FAILED")
    container, done, failed = project_clan_tree([done, failed])
    unread_ids = {done.identity, failed.identity}

    collapsed, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        fold_annotation=" ×2",
        unread_agent_ids=unread_ids,
    )
    expanded, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        is_expanded=True,
        unread_agent_ids=unread_ids,
    )

    assert "[F1 U2]" in collapsed.plain
    assert "[F1 U2]" in expanded.plain
    assert "D" not in collapsed.plain.split("[", 1)[1]
