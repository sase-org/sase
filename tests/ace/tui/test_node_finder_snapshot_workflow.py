"""Workflow-step and ordering snapshot tests for the Node Finder row model."""

from __future__ import annotations

from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.node_finder import filter_node_finder
from tests.ace.tui._member_jump_navigation_helpers import make_agent, make_clan
from tests.ace.tui._node_finder_snapshot_shared import (
    NodeFinderHarness,
    expand_all_nodes,
    snapshot_node_rows,
    snapshot_started,
)

__all__ = [
    "test_identities_unique_and_expanded_order_matches_tab",
    "test_non_agent_steps_are_context_only_or_omitted",
    "test_snapshot_filter_hints_map_to_identities",
    "test_starting_dismissed_and_hidden_only_parents_omitted",
    "test_synthetic_unknown_step_kind_is_excluded",
]


def _workflow_family() -> tuple[list[Agent], Agent, Agent, Agent, Agent]:
    started = snapshot_started()
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-wf",
        agent_name="wf",
        workflow="myflow",
    )
    bash = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="x",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="build",
        step_type="bash",
        step_index=0,
        total_steps=3,
        role_suffix="--build",
    )
    code = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="y",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf-step",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="code",
        step_type="agent",
        step_index=1,
        total_steps=3,
        role_suffix="--code",
    )
    pre = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="z",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf-pre",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="pre",
        step_type="python",
        step_index=0,
        total_steps=3,
        is_pre_prompt_step=True,
        role_suffix="--pre",
    )
    return [root, bash, code, pre], root, bash, code, pre


def test_non_agent_steps_are_context_only_or_omitted() -> None:
    complete, root, _bash, code, _pre = _workflow_family()
    app = NodeFinderHarness(complete, root)
    snap = build_node_finder_snapshot(app)
    names = [row.name for row in snapshot_node_rows(snap)]
    # The workflow root and its agent step are listed; bash/python/pre-prompt
    # steps have no jumpable descendants, so they are omitted.
    assert "wf" in names
    code_row = next(
        row for row in snapshot_node_rows(snap) if row.identity == code.identity
    )
    assert code_row.jumpable
    assert "x" not in names
    assert "z" not in names
    assert "the-bash-step" not in names


def test_synthetic_unknown_step_kind_is_excluded() -> None:
    complete, root, _bash, _code, _pre = _workflow_family()
    strange = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="q",
        project_file="/p/p.sase",
        status="DONE",
        start_time=snapshot_started(),
        raw_suffix="ts-wf-strange",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="strange",
        step_type="quantum",
        step_index=2,
        total_steps=4,
        role_suffix="--strange",
    )
    app = NodeFinderHarness(complete + [strange], root)
    snap = build_node_finder_snapshot(app)
    assert "the-quantum-step" not in [row.name for row in snapshot_node_rows(snap)]
    assert "the-strange-step" not in [row.name for row in snapshot_node_rows(snap)]


def test_starting_dismissed_and_hidden_only_parents_omitted() -> None:
    started = snapshot_started()
    visible = make_agent("visible")
    starting = make_agent("starting")
    starting.status = "STARTING"
    gone = make_agent("gone")
    hidden_root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="h",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-hidden-root",
        agent_name="h",
        workflow="hidden-flow",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hs",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-hidden-step",
        parent_workflow="hidden-flow",
        parent_timestamp="ts-hidden-root",
        step_name="setup",
        step_type="python",
        step_index=0,
        total_steps=1,
        is_hidden_step=True,
        role_suffix="--setup",
    )
    complete = [visible, starting, gone, hidden_root, hidden_step]
    app = NodeFinderHarness(complete, visible)
    app._dismissed_agents = {gone.identity}
    snap = build_node_finder_snapshot(app)
    names = [row.name for row in snapshot_node_rows(snap)]
    assert "visible" in names
    assert "starting" not in names
    assert "gone" not in names
    assert "h" not in names
    assert "the-setup-step" not in names


def test_identities_unique_and_expanded_order_matches_tab() -> None:
    projected, container = make_clan(3)
    app = NodeFinderHarness(projected, container)
    expand_all_nodes(app, projected)
    snap = build_node_finder_snapshot(app)
    identities = [row.identity for row in snapshot_node_rows(snap)]
    assert len(set(identities)) == len(identities)
    assert [row.name for row in snapshot_node_rows(snap)] == [
        agent.agent_name or agent.agent_clan for agent in app._agents
    ]


def test_snapshot_filter_hints_map_to_identities() -> None:
    projected, container = make_clan(3)
    app = NodeFinderHarness(projected, container)
    snap = build_node_finder_snapshot(app)
    view = filter_node_finder(snap, "")
    assert len(view.hint_to_identity) == snap.node_count
    assert set(view.hint_to_identity.values()) == {
        row.identity for row in snapshot_node_rows(snap) if row.jumpable
    }
    member_view = filter_node_finder(snap, "member-1")
    assert [row.name for row in member_view.rows if row.jumpable] == ["member-1"]
