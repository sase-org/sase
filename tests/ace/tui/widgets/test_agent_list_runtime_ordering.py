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


def test_sort_and_reorder_attaches_family_container_for_workflow_shaped_family() -> (
    None
):
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
    planner.total_steps = 2
    planner.agent_name = "ap5-plan"

    coder = agent(
        status="PLAN DONE",
        start=datetime(2026, 5, 17, 9, 10, 0),
        raw_suffix="20260517091000",
        cl_name="code",
        role_suffix="-code",
    )
    coder.parent_timestamp = parent_suffix
    coder.agent_name = "ap5-code"

    # apply_status_overrides normally populates followup_agents before
    # sort_and_reorder runs; simulate that state directly here.
    parent.followup_agents = [coder]

    ordered = sort_and_reorder([coder, parent], [planner])

    assert ordered[:3] == [parent, planner, coder]
    assert parent.is_family_container_row is True
    assert parent.family_container is None
    assert planner.family_container is parent
    assert coder.family_container is parent
    # A reference cycle between family_container and followup_agents must not
    # break dataclass eq/repr (compare=False, repr=False keeps it out).
    assert repr(coder)
    assert coder == coder


def test_sort_and_reorder_attaches_family_container_for_rename_on_attach_family() -> (
    None
):
    parent = agent(
        status="RUNNING",
        start=datetime(2026, 8, 2, 10, 0, 0),
        raw_suffix="20260802100000",
        cl_name="fam",
        role_suffix="--plan",
    )
    parent.agent_name = "fam--plan"
    parent.agent_family = "fam"
    parent.plan_chain_root = True
    child = agent(
        status="DONE",
        start=datetime(2026, 8, 2, 10, 1, 0),
        raw_suffix="20260802100100",
        cl_name="fam--code",
        role_suffix="--code",
    )
    child.parent_timestamp = parent.raw_suffix
    child.agent_name = "fam--code"
    parent.followup_agents = [child]

    sort_and_reorder([child, parent], [])

    assert parent.is_family_container_row is True
    assert child.family_container is parent
    assert parent.family_container is None


def test_sort_and_reorder_clears_stale_family_container_pointer() -> None:
    parent = agent(
        status="RUNNING",
        start=datetime(2026, 8, 2, 10, 0, 0),
        raw_suffix="20260802100000",
        cl_name="fam",
        role_suffix="--plan",
    )
    parent.agent_name = "fam--plan"
    parent.agent_family = "fam"
    parent.plan_chain_root = True
    child = agent(
        status="DONE",
        start=datetime(2026, 8, 2, 10, 1, 0),
        raw_suffix="20260802100100",
        cl_name="fam--code",
        role_suffix="--code",
    )
    child.parent_timestamp = parent.raw_suffix
    child.agent_name = "fam--code"
    parent.followup_agents = [child]

    sort_and_reorder([child, parent], [])
    assert child.family_container is parent

    # The family dissolves (e.g. the follow-up is dismissed); a re-run must
    # not leave a stale pointer even though ``child`` is still passed in.
    parent.followup_agents = []
    sort_and_reorder([child, parent], [])

    assert parent.is_family_container_row is False
    assert child.family_container is None


def test_sort_and_reorder_skips_synthetic_planner_and_parallel_family_rows() -> None:
    parent = agent(
        status="RUNNING",
        start=datetime(2026, 8, 2, 11, 0, 0),
        raw_suffix="20260802110000",
        cl_name="fam2",
        role_suffix="--plan",
    )
    parent.agent_name = "fam2--plan"
    parent.agent_family = "fam2"
    parent.plan_chain_root = True

    synthetic = agent(
        status="RUNNING",
        start=datetime(2026, 8, 2, 11, 1, 0),
        raw_suffix="20260802110100",
        cl_name="fam2--0",
    )
    synthetic.parent_timestamp = parent.raw_suffix
    synthetic.is_synthetic_planner = True

    parallel = agent(
        status="RUNNING",
        start=datetime(2026, 8, 2, 11, 2, 0),
        raw_suffix="20260802110200",
        cl_name="fam2--parallel",
    )
    parallel.parent_timestamp = parent.raw_suffix
    parallel.agent_family_parallel = True

    real_child = agent(
        status="DONE",
        start=datetime(2026, 8, 2, 11, 3, 0),
        raw_suffix="20260802110300",
        cl_name="fam2--code",
        role_suffix="--code",
    )
    real_child.parent_timestamp = parent.raw_suffix
    real_child.agent_name = "fam2--code"

    parent.followup_agents = [synthetic, parallel, real_child]

    sort_and_reorder([synthetic, parallel, real_child, parent], [])

    assert parent.is_family_container_row is True
    assert synthetic.family_container is None
    assert parallel.family_container is None
    assert real_child.family_container is parent
