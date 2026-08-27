"""Wire-mirror tests for workflow prompt-step enrichment from parent metadata.

Mirrors ``tests/test_workflow_child_meta_enrichment.py`` scenario-for-scenario,
but drives ``enrich_agent_from_meta_wire(..., workflow_child=True)`` instead of
the filesystem-backed helper, so the snapshot-sourced fast path used by
``_build_workflow_agent_steps_for_record`` stays behaviorally identical to the
per-step filesystem re-read it replaces.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_wire import AgentMetaWire


def _workflow_step(
    step_type: str,
    *,
    status: str = "DONE",
    parent_step_index: int | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=step_type,
        project_file="/tmp/p.sase",
        status=status,
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        parent_workflow="agent-family",
        parent_timestamp="20260519090000",
        step_type=step_type,
        step_index=0,
        total_steps=3,
        parent_step_index=parent_step_index,
    )


def test_workflow_child_enrichment_derives_planner_identity_only_for_main_agent() -> (
    None
):
    meta = AgentMetaWire(
        name="ap5",
        agent_family="ap5",
        agent_family_role="root",
        plan_chain_root=True,
        role_suffix="-plan",
        model="gpt-test",
        llm_provider="codex",
        workspace_dir="/tmp/workspace",
        plan_submitted_at=["2026-05-19T13:00:00Z"],
    )
    planner = _workflow_step("agent")
    bash = _workflow_step("bash")

    enrich_agent_from_meta_wire(planner, meta, None, workflow_child=True)
    enrich_agent_from_meta_wire(bash, meta, None, workflow_child=True)

    assert planner.agent_name == "ap5--plan"
    assert planner.agent_family == "ap5"
    assert planner.agent_family_role == "plan"
    assert planner.role_suffix == "--plan"
    assert planner.plan_chain_root is False

    assert bash.agent_name is None
    assert bash.agent_family is None
    assert bash.agent_family_role is None
    assert bash.role_suffix is None
    assert bash.plan_chain_root is False

    assert planner.model == "gpt-test"
    assert bash.model == "gpt-test"
    assert planner.plan_times
    assert bash.plan_times


def test_workflow_child_enrichment_uses_generic_root_suffix() -> None:
    meta = AgentMetaWire(
        name="ap5",
        agent_family="ap5",
        agent_family_role="root",
        plan_chain_root=True,
        role_suffix="--0",
    )
    question_child = _workflow_step("agent")

    enrich_agent_from_meta_wire(question_child, meta, None, workflow_child=True)

    assert question_child.agent_name == "ap5--0"
    assert question_child.agent_family == "ap5"
    assert question_child.agent_family_role is None
    assert question_child.role_suffix == "--0"


@pytest.mark.parametrize(
    ("auto_approve_plan_action", "approve", "expected_action"),
    [
        ("epic", False, "epic"),
        (None, True, None),
    ],
)
def test_workflow_child_enrichment_applies_auto_approve_only_to_main_agent(
    auto_approve_plan_action: str | None,
    approve: bool,
    expected_action: str | None,
) -> None:
    meta = AgentMetaWire(
        auto_approve_plan_action=auto_approve_plan_action, approve=approve
    )
    main_agent = _workflow_step("agent")
    bash = _workflow_step("bash")
    python = _workflow_step("python")
    embedded_agent = _workflow_step("agent", parent_step_index=0)

    for agent in (main_agent, bash, python, embedded_agent):
        enrich_agent_from_meta_wire(agent, meta, None, workflow_child=True)

    assert main_agent.approve is True
    assert main_agent.auto_approve_plan_action == expected_action

    for agent in (bash, python, embedded_agent):
        assert agent.approve is False
        assert agent.auto_approve_plan_action is None


@pytest.mark.parametrize(
    ("auto_approve_plan_action", "approve"),
    [
        ("epic", False),
        (None, True),
    ],
)
def test_workflow_child_plan_status_uses_suppressed_meta_auto_approve(
    auto_approve_plan_action: str | None,
    approve: bool,
) -> None:
    meta = AgentMetaWire(
        plan=True,
        plan_submitted_at=["2026-05-19T13:00:00Z"],
        auto_approve_plan_action=auto_approve_plan_action,
        approve=approve,
    )
    bash = _workflow_step("bash", status="RUNNING")

    enrich_agent_from_meta_wire(bash, meta, None, workflow_child=True)

    assert bash.status == "RUNNING"
    assert bash.approve is False
    assert bash.auto_approve_plan_action is None
