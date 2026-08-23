"""Agent fixtures shared by Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_ordering import sort_and_reorder
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


def waiting_family_child_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 5, 21, 0, 0),
        raw_suffix="20260705-210000-parent",
        agent_name="visual-parent",
        agent_family="visual-parent",
        agent_family_role="root",
        llm_provider="codex",
        model="gpt-5",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent--reviewer",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 5, 21, 1, 0),
        run_start_time=None,
        wait_start_time=datetime(2026, 7, 5, 21, 1, 0),
        raw_suffix="20260705-210100-reviewer",
        parent_timestamp=parent.raw_suffix,
        agent_name="visual-parent--reviewer",
        agent_family="visual-parent",
        agent_family_role="reviewer",
        role_suffix="--reviewer",
        waiting_for=["visual-parent"],
        llm_provider="codex",
        model="gpt-5",
    )
    parent.followup_agents = [child]
    return [parent, child]


def running_family_runtime_agents() -> list[Agent]:
    started = datetime(2026, 7, 19, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visual-runtime-family",
        project_file="/workspace/sase/visual_project.sase",
        status="WORKING TALE",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260719090000",
        agent_name="visual-runtime-family--plan",
        agent_family="visual-runtime-family",
        agent_family_role="root",
        plan_chain_root=True,
        workflow="ace-run",
        llm_provider="codex",
        model="gpt-5",
    )
    planner = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="plan",
        project_file=root.project_file,
        status="DONE",
        start_time=started,
        run_start_time=started,
        raw_suffix=root.raw_suffix,
        parent_workflow=root.workflow,
        parent_timestamp=root.raw_suffix,
        step_name="plan",
        step_type="agent",
        step_index=0,
        total_steps=1,
        plan_times=[started + timedelta(minutes=2)],
        role_suffix="--plan",
        agent_name="visual-runtime-family--plan",
        agent_family="visual-runtime-family",
        agent_family_role="plan",
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-runtime-family-code",
        project_file=root.project_file,
        status="RUNNING",
        start_time=started + timedelta(minutes=4),
        run_start_time=started + timedelta(minutes=4),
        raw_suffix="20260719090400",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="visual-runtime-family--code",
        agent_family="visual-runtime-family",
        agent_family_role="code",
        llm_provider="codex",
        model="gpt-5",
    )
    root.followup_agents.append(coder)
    root.runtime_children.extend([planner, coder])
    return [root, planner, coder]


def settled_monitor_family_agents() -> list[Agent]:
    """Return a collapsed family mixing one running and three finished monitors.

    Finished monitors mix a clean completion, a failure, and an explicit stop
    so the grey settled badge is proven to read as "finished", not merely
    "succeeded".
    """
    started = datetime(2026, 7, 26, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-monitor-family",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260726-090000-root",
        agent_name="visual-monitor-family--0",
        agent_family="visual-monitor-family",
        agent_family_role="root",
        role_suffix="--0",
        llm_provider="codex",
        model="gpt-5",
    )

    def _monitor(
        suffix: str,
        *,
        monitor_state: str,
        minute_offset: int,
        stop_offset: int | None,
        exit_code: int | None = None,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-monitor-family--{suffix}",
            project_file="/workspace/sase/visual_project.sase",
            status="MONITORING" if monitor_state == "running" else "MONITORED",
            start_time=started + timedelta(minutes=minute_offset),
            stop_time=(
                started + timedelta(minutes=stop_offset)
                if stop_offset is not None
                else None
            ),
            raw_suffix=f"20260726-0901{minute_offset:02d}-{suffix}",
            parent_timestamp=root.raw_suffix,
            agent_name=f"visual-monitor-family--{suffix}",
            agent_family="visual-monitor-family",
            agent_family_role="monitor",
            role_suffix=f"--{suffix}",
            monitor_id=f"mon-{suffix}",
            monitor_state=monitor_state,
            monitor_label=f"visual {suffix}",
            monitor_start_status="MONITORING",
            monitor_stop_status="MONITORED",
            monitor_exit_code=exit_code,
            llm_provider="codex",
            model="gpt-5",
        )

    running_monitor = _monitor(
        "mon1", monitor_state="running", minute_offset=1, stop_offset=None
    )
    completed_monitor = _monitor(
        "mon2",
        monitor_state="completed",
        minute_offset=2,
        stop_offset=6,
        exit_code=0,
    )
    failed_monitor = _monitor(
        "mon3",
        monitor_state="failed",
        minute_offset=3,
        stop_offset=7,
        exit_code=1,
    )
    stopped_monitor = _monitor(
        "mon4", monitor_state="stopped", minute_offset=4, stop_offset=8, exit_code=0
    )
    root.followup_agents = [
        running_monitor,
        completed_monitor,
        failed_monitor,
        stopped_monitor,
    ]
    return [root, running_monitor, completed_monitor, failed_monitor, stopped_monitor]


def parent_navigation_family_agents() -> list[Agent]:
    """Return a loader-shaped plan family with a hidden Python pre-step."""
    started = datetime(2026, 7, 22, 6, 0, 0)
    stopped = datetime(2026, 7, 22, 6, 10, 0)
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visual-house-navigation",
        project_file="/workspace/sase/visual_project.sase",
        status="PLAN APPROVED",
        start_time=started,
        stop_time=stopped,
        raw_suffix="20260722060000",
        agent_name="visual-nav",
        agent_family="visual-nav",
        agent_family_role="root",
        plan_chain_root=True,
        workflow="ace-run",
        llm_provider="codex",
        model="gpt-5",
    )

    def workflow_step(
        name: str,
        step_type: str,
        step_index: int,
        *,
        hidden: bool = False,
        pre_prompt: bool = False,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=name,
            project_file=root.project_file,
            status="DONE",
            start_time=started,
            stop_time=stopped,
            raw_suffix=root.raw_suffix,
            parent_workflow="ace-run",
            parent_timestamp=root.raw_suffix,
            step_name=name,
            step_type=step_type,
            step_index=step_index,
            total_steps=4,
            is_hidden_step=hidden,
            is_pre_prompt_step=pre_prompt,
            embedded_workflow_name="git" if pre_prompt else None,
        )

    main = workflow_step("main", "agent", 0)
    main.agent_name = "visual-nav--plan"
    prepare = workflow_step("prepare", "bash", 1)
    setup = workflow_step("setup", "python", 2, hidden=True, pre_prompt=True)
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-house-navigation-code",
        project_file=root.project_file,
        status="DONE",
        start_time=datetime(2026, 7, 22, 6, 11, 0),
        stop_time=datetime(2026, 7, 22, 6, 20, 0),
        raw_suffix="20260722061100",
        parent_timestamp=root.raw_suffix,
        agent_name="visual-nav--code",
        agent_family="visual-nav",
        agent_family_role="code",
        llm_provider="codex",
        model="gpt-5",
    )
    root.followup_agents.append(coder)
    root.runtime_children.extend([main, coder])
    return [root, main, coder, prepare, setup]


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


def parallel_family_agents() -> list[Agent]:
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parallel-family",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 16, 10, 0, 0),
        raw_suffix="20260716100000",
        agent_name="visual-parallel-family",
        agent_family="visual-parallel-family",
        agent_family_role="root",
        agent_family_parallel=True,
        llm_provider="codex",
        model="gpt-5",
    )
    members = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-parallel-phase-{index}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=datetime(2026, 7, 16, 10, index, 0),
            run_start_time=(
                datetime(2026, 7, 16, 10, index, 30) if status == "RUNNING" else None
            ),
            stop_time=(datetime(2026, 7, 16, 10, 6, 0) if status == "DONE" else None),
            raw_suffix=f"20260716100{index}00",
            parent_timestamp=root.raw_suffix,
            agent_name=f"visual-parallel-phase-{index}",
            agent_family="visual-parallel-family",
            agent_family_role="phase",
            agent_family_parallel=True,
            llm_provider="codex",
            model="gpt-5",
        )
        for index, status in enumerate(("RUNNING", "RUNNING", "DONE"), start=1)
    ]
    rows = [root, *members]
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


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
    question = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars--q",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 3, 0),
        stop_time=datetime(2026, 7, 8, 9, 5, 0),
        raw_suffix="20260708090300",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--q",
        agent_name="visual-output-vars--q",
        agent_family="visual-output-vars",
        agent_family_role="q",
        output_variables={
            "answer_path": "/workspace/sase/out/user-answer.md",
            "summary": "approval captured",
        },
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [parent, coder, question]
    _apply_status_overrides(rows)
    return rows


def renamed_generic_family_agents() -> list[Agent]:
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visual-family-root",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 11, 0, 0),
        stop_time=datetime(2026, 7, 18, 11, 4, 0),
        raw_suffix="20260718110000",
        workflow="ace(run)",
        role_suffix="--0",
        agent_name="cx--0",
        agent_family="cx",
        agent_family_role="root",
        appears_as_agent=True,
        llm_provider="codex",
        model="gpt-5",
    )
    main = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 11, 0, 0),
        stop_time=datetime(2026, 7, 18, 11, 4, 0),
        raw_suffix=root.raw_suffix,
        workflow=root.workflow,
        parent_workflow=root.workflow,
        parent_timestamp=root.raw_suffix,
        step_name="main",
        step_type="agent",
        step_index=0,
        total_steps=1,
        parent_appears_as_agent=True,
        role_suffix="--0",
        agent_name="cx--0",
        agent_family="cx",
        agent_family_role="main",
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 11, 5, 0),
        stop_time=datetime(2026, 7, 18, 11, 10, 0),
        raw_suffix="20260718110500",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="cx--code",
        agent_family="cx",
        agent_family_role="code",
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [root, main, coder]
    _apply_status_overrides([root, coder], [main])
    return rows


def family_and_lone_planner_agents() -> list[Agent]:
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-real-family",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        stop_time=datetime(2026, 7, 18, 12, 4, 0),
        raw_suffix="20260718120000",
        role_suffix="--plan",
        agent_name="visual-real-family--plan",
        agent_family="visual-real-family",
        agent_family_role="root",
        plan_chain_root=True,
        appears_as_agent=True,
    )
    member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-real-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 5, 0),
        stop_time=datetime(2026, 7, 18, 12, 8, 0),
        raw_suffix="20260718120500",
        parent_timestamp=family.raw_suffix,
        role_suffix="--code",
        agent_name="visual-real-family--code",
        agent_family="visual-real-family",
        agent_family_role="code",
    )
    lone_planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-lone-planner",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 10, 0),
        stop_time=datetime(2026, 7, 18, 12, 15, 0),
        raw_suffix="20260718121000",
        role_suffix="--plan",
        agent_name="visual-lone-planner--plan",
        agent_family="visual-lone-planner",
        agent_family_role="root",
        plan_chain_root=True,
        appears_as_agent=True,
    )
    rows = [family, member, lone_planner]
    _apply_status_overrides(rows)
    return rows
