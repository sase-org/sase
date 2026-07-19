"""Concrete sequential family-member projection tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import (
    _concrete_agent_rows,
    concrete_family_member_rows,
    family_member_status_buckets,
)

_STARTED = datetime(2026, 7, 19, 9, 0, 0)


def _agent(
    name: str,
    *,
    role: str,
    parent_timestamp: str | None = None,
    workflow_child: bool = False,
    start_offset: int = 0,
    status: str = "DONE",
    step_type: str = "agent",
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/family.sase",
        status=status,
        start_time=_STARTED + timedelta(minutes=start_offset),
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent_timestamp,
        agent_name=name,
        agent_family="alpha",
        agent_family_role=role,
        role_suffix=f"--{role}",
    )
    if workflow_child:
        agent.parent_workflow = "ace-run"
        agent.step_type = step_type
    return agent


def _plan_root(*, name: str = "alpha--plan") -> Agent:
    root = _agent(name, role="root")
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    return root


def test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe() -> None:
    root = _plan_root()
    planner = _agent(
        "alpha--plan-step",
        role="plan",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
    )
    feedback = _agent(
        "alpha--2",
        role="feedback",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    synthetic = _agent(
        "alpha--synthetic-plan",
        role="plan",
        parent_timestamp=root.raw_suffix,
    )
    synthetic.is_synthetic_planner = True
    parallel = _agent(
        "alpha--parallel",
        role="review",
        parent_timestamp=root.raw_suffix,
    )
    parallel.agent_family_parallel = True

    root.runtime_children = [planner, feedback, coder, synthetic, parallel]
    root.followup_agents = [synthetic, feedback, coder, parallel]

    assert concrete_family_member_rows(root) == (planner, feedback, coder)


def test_rename_on_attach_root_remains_the_first_real_member() -> None:
    root = _agent("alpha--0", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert concrete_family_member_rows(root) == (root, coder)


def test_plan_root_without_concrete_planner_uses_root_fallback() -> None:
    root = _plan_root(name="alpha")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    synthetic = _agent(
        "alpha--synthetic-plan",
        role="plan",
        parent_timestamp=root.raw_suffix,
    )
    synthetic.is_synthetic_planner = True
    root.runtime_children = [synthetic, coder]
    root.followup_agents = [synthetic, coder]

    assert concrete_family_member_rows(root) == (root, coder)


def test_bare_non_plan_container_stays_execution_neutral() -> None:
    root = _agent("alpha", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [coder]

    assert concrete_family_member_rows(root) == (coder,)


def test_workflow_aggregate_projects_only_loaded_agent_steps() -> None:
    root = _agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    main = _agent(
        "workflow-main",
        role="main",
        workflow_child=True,
    )
    python_step = _agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [main, python_step]

    assert _concrete_agent_rows(root) == (main,)
    assert _concrete_agent_rows(python_step) == ()


def test_workflow_without_loaded_agent_steps_falls_back_to_root() -> None:
    root = _agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    python_step = _agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [python_step]

    assert _concrete_agent_rows(root) == (root,)


def test_approved_non_final_family_member_projects_done() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="TALE APPROVED",
    )
    coder = _agent(
        "alpha--code",
        role="code",
        status="WORKING TALE",
    )

    assert family_member_status_buckets((planner, coder)) == ("Done", "Running")


def test_approved_final_family_member_keeps_global_running_bucket() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="PLAN APPROVED",
    )

    assert family_member_status_buckets((planner,)) == ("Running",)
