"""Tests for runtime child ordering and attachment."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent_groups._buckets import status_bucket_for
from sase.ace.tui.models.agent import AgentType

from .agent_list_runtime_helpers import agent, workflow_child


def test_sort_and_reorder_populates_runtime_children_idempotently() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        raw_suffix="20260425140000",
        cl_name="parent",
    )
    planner = workflow_child(
        step_type="agent",
        raw_suffix="20260425140100",
        cl_name="plan",
    )
    shell = workflow_child(
        step_type="bash",
        raw_suffix="20260425140200",
        cl_name="shell",
    )
    embedded = workflow_child(
        step_type="agent",
        raw_suffix="20260425140300",
        cl_name="embedded",
    )
    embedded.parent_step_index = 0
    coder = agent(
        raw_suffix="20260425140400",
        cl_name="code",
    )
    coder.parent_timestamp = "20260425140000"

    sort_and_reorder([parent, coder], [planner, shell, embedded])
    sort_and_reorder([parent, coder], [planner, shell, embedded])

    assert parent.runtime_children == [planner, coder]


def test_sort_and_reorder_drops_followup_without_parent() -> None:
    orphan = agent(
        raw_suffix="20260425140400",
        cl_name="code",
    )
    orphan.parent_timestamp = "missing-parent"

    assert sort_and_reorder([orphan], []) == []


def test_sort_reorder_runtime_children_ignore_step_suffix_collision() -> None:
    parent_suffix = "20260506130900"
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN APPROVED",
        raw_suffix=parent_suffix,
        cl_name="aga.r1.plan",
        role_suffix=".plan",
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 6, 13, 9, 0),
        run_start=datetime(2026, 5, 6, 13, 10, 7),
        plan_times=[datetime(2026, 5, 6, 13, 14, 53)],
        raw_suffix=parent_suffix,
        cl_name="plan",
        role_suffix=".plan",
        parent_appears_as_agent=True,
    )
    planner.parent_timestamp = parent_suffix
    resolve = workflow_child(
        step_type="bash",
        status="DONE",
        raw_suffix=parent_suffix,
        cl_name="resolve",
    )
    resolve.parent_timestamp = parent_suffix
    resolve.is_hidden_step = True
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 5, 6, 13, 15, 10),
        run_start=datetime(2026, 5, 6, 13, 15, 10),
        raw_suffix="20260506131510",
        cl_name="aga.r1.code",
        role_suffix=".code",
    )
    coder.parent_timestamp = parent_suffix

    sort_and_reorder([parent, coder], [planner, resolve])

    assert parent.runtime_children == [planner, coder]
    assert resolve.runtime_children == []
    assert planner.runtime_children == []


def test_sort_and_reorder_keeps_agent_family_children_nested_under_root() -> None:
    parent_suffix = "20260517085500"
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN DONE",
        start=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix=parent_suffix,
        cl_name="agent-family",
        role_suffix="-plan",
    )
    parent.workflow = "agent-family"
    parent.agent_name = "ap5"
    parent.agent_family = "ap5"
    parent.agent_family_role = "root"
    parent.plan_chain_root = True

    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix=parent_suffix,
        cl_name="main",
        role_suffix="-plan",
    )
    planner.parent_timestamp = parent_suffix
    planner.step_index = 0
    planner.total_steps = 3
    planner.agent_name = "ap5-plan"

    bash = workflow_child(
        step_type="bash",
        status="DONE",
        start=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix=parent_suffix,
        cl_name="resolve",
    )
    bash.parent_timestamp = parent_suffix
    bash.step_index = 1
    bash.total_steps = 3

    python = workflow_child(
        step_type="python",
        status="DONE",
        start=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix=parent_suffix,
        cl_name="summarize",
    )
    python.parent_timestamp = parent_suffix
    python.step_index = 2
    python.total_steps = 3

    coder = agent(
        status="PLAN DONE",
        start=datetime(2026, 5, 17, 9, 10, 0),
        raw_suffix="20260517091000",
        cl_name="code",
        role_suffix="-code",
    )
    coder.parent_timestamp = parent_suffix
    coder.agent_name = "ap5-code"

    ordered = sort_and_reorder([coder, parent], [python, bash, planner])

    assert ordered == [parent, planner, coder, bash, python]


def test_waiting_family_child_orders_under_running_parent_and_buckets_waiting() -> None:
    parent = agent(
        status="RUNNING",
        start=datetime(2026, 7, 5, 21, 0, 0),
        raw_suffix="20260705210000",
        cl_name="parent",
    )
    child = agent(
        status="WAITING",
        start=datetime(2026, 7, 5, 21, 1, 0),
        run_start=None,
        raw_suffix="20260705210100",
        cl_name="parent--reviewer",
    )
    child.parent_timestamp = parent.raw_suffix
    child.waiting_for = ["parent"]

    ordered = sort_and_reorder([child, parent], [])

    assert ordered == [parent, child]
    assert parent.runtime_children == [child]
    assert child.is_family_member_child
    assert status_bucket_for(child) == "Waiting"
