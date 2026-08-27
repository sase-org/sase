"""Agent fixtures shared by Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def plan_handoff_status_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN APPROVED",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            raw_suffix="20260509-100000-plan-approved",
            agent_name="plan.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-tale-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="TALE APPROVED",
            start_time=datetime(2026, 5, 9, 10, 1, 0),
            raw_suffix="20260509-100100-tale-approved",
            agent_name="tale.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING PLAN",
            start_time=datetime(2026, 5, 9, 10, 2, 0),
            raw_suffix="20260509-100200-working-plan",
            agent_name="working.plan",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-tale",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING TALE",
            start_time=datetime(2026, 5, 9, 10, 3, 0),
            raw_suffix="20260509-100300-working-tale",
            agent_name="working.tale",
        ),
    ]


def group_lane_collapse_precedence_agents() -> list[Agent]:
    """Return three Running lanes with workflow and family descendants."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 22, 7, 0, 0)

    def workflow_lane(name: str, minute: int) -> tuple[Agent, Agent, Agent]:
        fold_key = f"2026072207{minute:02d}00"
        root = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=f"visual-{name}",
            project_file=project_file,
            status="RUNNING",
            start_time=started.replace(minute=minute),
            raw_suffix=fold_key,
            agent_name=name,
            workflow=f"{name}-workflow",
            llm_provider="codex",
            model="gpt-5",
        )
        agent_step = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=f"{name}-agent-step",
            project_file=project_file,
            status="RUNNING",
            start_time=root.start_time,
            raw_suffix=fold_key,
            parent_timestamp=fold_key,
            parent_workflow=root.workflow,
            step_name="implement",
            step_type="agent",
        )
        hidden_step = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=f"{name}-prepare-step",
            project_file=project_file,
            status="DONE",
            start_time=root.start_time,
            raw_suffix=fold_key,
            parent_timestamp=fold_key,
            parent_workflow=root.workflow,
            step_name="prepare",
            step_type="python",
            is_hidden_step=True,
            is_pre_prompt_step=True,
        )
        root.runtime_children.extend([agent_step, hidden_step])
        return root, agent_step, hidden_step

    hu = workflow_lane("hu", 0)
    ht = workflow_lane("ht", 1)

    hs_root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-hs",
        project_file=project_file,
        status="RUNNING",
        start_time=started.replace(minute=2),
        raw_suffix="20260722070200",
        agent_name="hs",
        agent_family="hs",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider="codex",
        model="gpt-5",
    )
    hs_member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-hs-code",
        project_file=project_file,
        status="RUNNING",
        start_time=started.replace(minute=3),
        raw_suffix="20260722070300",
        parent_timestamp=hs_root.raw_suffix,
        agent_name="hs--code",
        agent_family="hs",
        agent_family_role="code",
        llm_provider="codex",
        model="gpt-5",
    )
    hs_root.followup_agents.append(hs_member)
    hs_root.runtime_children.append(hs_member)
    return [*hu, *ht, hs_root, hs_member]


def runner_slot_wait_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-drain-barrier",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 1, 0),
            raw_suffix="20260712120100",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260712120100",
            agent_name="drain-barrier",
            pid=4102,
            wait_runners=0,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-12T16:01:00Z",
            runner_slots_in_use=0,
            runner_slot_queue_position=2,
            runner_slot_queue_size=2,
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-global-cap",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 0, 0),
            raw_suffix="20260712120000",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260712120000",
            agent_name="global-cap",
            pid=4101,
            wait_runners=9,
            wait_runners_explicit=False,
            slot_requested_at="2026-07-12T16:00:00Z",
            runner_slots_in_use=0,
            runner_slot_queue_position=1,
            runner_slot_queue_size=2,
            llm_provider="claude",
            model="sonnet",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-dependency-wait",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 11, 59, 0),
            raw_suffix="20260712115900",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260712115900",
            agent_name="dependency-wait",
            pid=4103,
            waiting_for=["visual-upstream"],
            llm_provider="qwen",
            model="qwen3-coder",
        ),
    ]


def reserved_tribe_wait_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-reswait",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 28, 12, 0, 0),
            raw_suffix="20260728120000",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260728120000",
            agent_name="reswait",
            pid=4301,
            waiting_for=["@default"],
            llm_provider="codex",
            model="gpt-5",
        ),
    ]


def runner_slot_queue_window_agents() -> list[Agent]:
    """Return a long queue with both ladder gaps and visible ordering clues."""
    rows: list[Agent] = []
    for rank in range(1, 10):
        name = (
            "drain-barrier"
            if rank == 1
            else ("queue-middle" if rank == 6 else f"waiter-{rank:02d}")
        )
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name=f"visual-queue-{rank:02d}",
                project_file="/workspace/sase/visual_project.sase",
                status="WAITING",
                start_time=datetime(2026, 7, 25, 12, rank, 0),
                raw_suffix=f"2026072512{rank:02d}00",
                artifacts_dir=(
                    f"/workspace/sase/artifacts/ace-run/2026072512{rank:02d}00"
                ),
                agent_name=name,
                pid=4200 + rank,
                wait_runners=0 if rank == 1 else 9,
                wait_runners_explicit=rank == 1,
                wait_priority=1 if rank == 1 else None,
                wait_priority_explicit=rank == 1,
                slot_requested_at=f"2026-07-25T16:{rank:02d}:00Z",
                llm_provider="codex",
                model="gpt-5",
            )
        )
    return rows


def output_variable_family_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 0, 0),
        stop_time=datetime(2026, 7, 8, 9, 9, 0),
        raw_suffix="20260708090000",
        role_suffix="--plan",
        agent_name="visual-output-vars",
        agent_family="visual-output-vars",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars--code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 1, 0),
        stop_time=datetime(2026, 7, 8, 9, 7, 0),
        raw_suffix="20260708090100",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--code",
        agent_name="visual-output-vars--code",
        agent_family="visual-output-vars",
        agent_family_role="code",
        output_variables={
            "build_report": "/workspace/sase/out/build-report.md",
            "summary": "tests passed\ncoverage updated",
        },
        llm_provider="codex",
        model="gpt-5",
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars--1",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 3, 0),
        stop_time=datetime(2026, 7, 8, 9, 5, 0),
        raw_suffix="20260708090300",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--1",
        agent_name="visual-output-vars--1",
        agent_family="visual-output-vars",
        agent_family_role="review",
        output_variables={
            "answer_path": "/workspace/sase/out/user-answer.md",
            "summary": "approval captured",
        },
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [parent, coder, continuation]
    _apply_status_overrides(rows)
    return rows
