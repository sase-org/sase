"""Synthetic composed-agent corpus for Phase 1 compose goldens."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType


def _ts(raw: str) -> datetime:
    return datetime.strptime(raw, "%Y%m%d%H%M%S")


def build_golden_agents() -> list[Agent]:
    """Return composed agents covering the contract-sensitive row shapes."""

    project_file = "/tmp/sase/projects/demo/demo.gp"
    plan = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo_plan",
        project_file=project_file,
        status="PLAN APPROVED",
        start_time=_ts("20260501090000"),
        stop_time=_ts("20260501090500"),
        raw_suffix="20260501090000",
        workflow="three_phase",
        role_suffix=".plan",
        appears_as_agent=True,
        plan_times=[datetime.fromisoformat("2026-05-01T09:04:00")],
        code_time=datetime.fromisoformat("2026-05-01T09:08:00"),
        diff_path="/tmp/diffs/demo.diff",
        step_output={"meta_commit_message": "ship it"},
    )
    code = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo_plan",
        project_file=project_file,
        status="RUNNING",
        start_time=_ts("20260501090800"),
        raw_suffix="20260501090800",
        role_suffix=".code",
        parent_timestamp=plan.raw_suffix,
        pid=4242,
        workspace_num=17,
        model="gpt-5.5",
        llm_provider="codex",
        vcs_provider="GitHub",
        agent_name="demo-code",
        step_index=0,
        total_steps=1,
    )
    plan.followup_agents.append(code)

    question = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="needs_answer",
        project_file=project_file,
        status="QUESTION",
        start_time=_ts("20260501101000"),
        stop_time=_ts("20260501102000"),
        raw_suffix="20260501101000",
        questions_times=[datetime.fromisoformat("2026-05-01T10:19:00")],
        response_path="/tmp/responses/question.md",
    )

    retried_parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry_case",
        project_file=project_file,
        status="FAILED",
        start_time=_ts("20260501110000"),
        stop_time=_ts("20260501110100"),
        raw_suffix="20260501110000",
        retried_as_timestamp="20260501110200",
        retry_terminal=True,
        retry_error_category="transient",
        error_message="temporary failure",
    )
    retry_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry_case",
        project_file=project_file,
        status="RUNNING",
        start_time=_ts("20260501110200"),
        raw_suffix="20260501110200",
        pid=5252,
        retry_of_timestamp=retried_parent.raw_suffix,
        retry_attempt=1,
        retry_chain_root_timestamp=retried_parent.raw_suffix,
    )
    retried_parent.retry_chain_siblings.append(retry_child)

    workflow_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo_plan",
        project_file=project_file,
        status="DONE",
        start_time=_ts("20260501090100"),
        stop_time=_ts("20260501090200"),
        raw_suffix="20260501090100",
        parent_workflow="three_phase",
        parent_timestamp=plan.raw_suffix,
        step_name="plan",
        step_type="agent",
        step_output={"plan_path": "/tmp/plans/demo.md"},
        step_index=0,
        total_steps=2,
        artifacts_dir="/tmp/artifacts/three_phase/20260501090100",
    )

    return [plan, workflow_step, code, question, retried_parent, retry_child]


def fixture_summary() -> dict[str, object]:
    agents = build_golden_agents()
    return {
        "count": len(agents),
        "statuses": sorted({agent.status for agent in agents}),
        "has_followup": any(agent.followup_agents for agent in agents),
        "has_retry_chain": any(agent.retry_chain_siblings for agent in agents),
        "has_workflow_child": any(agent.parent_workflow for agent in agents),
    }
