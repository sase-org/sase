"""Clan fixtures shared by Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType


def clan_tree_agents(*, clan_summary: str | None = None) -> list[Agent]:
    generation = "20260717100000"
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-family",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 2, 0),
        run_start_time=datetime(2026, 7, 17, 10, 2, 0),
        raw_suffix="20260717100200-family",
        agent_name="research.family",
        agent_clan="research",
        agent_clan_generation=generation,
        clan_summary=clan_summary,
        agent_family="research.family",
        agent_family_role="root",
        tribe="epic",
        llm_provider="codex",
        model="gpt-5",
    )
    family_member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 4, 0),
        run_start_time=datetime(2026, 7, 17, 10, 4, 0),
        raw_suffix="20260717100400-family-code",
        parent_timestamp=family.raw_suffix,
        role_suffix="--code",
        agent_name="research.family--code",
        agent_family="research.family",
        agent_family_role="code",
        agent_clan="research",
        agent_clan_generation=generation,
        llm_provider="codex",
        model="gpt-5",
    )
    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visual-research-audit",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        stop_time=datetime(2026, 7, 17, 10, 8, 0),
        raw_suffix="20260717100000-audit",
        workflow="audit",
        agent_name="research.audit",
        agent_clan="research",
        agent_clan_generation=generation,
        tribe="review",
    )
    workflow_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="audit-prompt",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 1, 0),
        run_start_time=datetime(2026, 7, 17, 10, 1, 0),
        stop_time=datetime(2026, 7, 17, 10, 7, 0),
        raw_suffix="20260717100100-audit-prompt",
        parent_workflow="audit",
        parent_timestamp=workflow.raw_suffix,
        agent_family="research.audit",
        step_name="audit",
        step_type="agent",
        step_index=0,
        total_steps=2,
        llm_provider="claude",
        model="sonnet",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="audit-setup",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 0, 30),
        run_start_time=datetime(2026, 7, 17, 10, 0, 30),
        stop_time=datetime(2026, 7, 17, 10, 0, 45),
        raw_suffix="20260717100030-audit-setup",
        parent_workflow="audit",
        parent_timestamp=workflow.raw_suffix,
        agent_family="research.audit",
        step_name="setup",
        step_type="bash",
        step_index=1,
        total_steps=2,
        is_hidden_step=True,
    )
    waiting = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-waiting",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 17, 10, 3, 0),
        raw_suffix="20260717100300-waiting",
        agent_name="research.waiting",
        agent_clan="research",
        agent_clan_generation=generation,
        tribe="epic",
        waiting_for=["research.family"],
        llm_provider="gemini",
        model="gemini-pro",
    )
    return sort_and_reorder(
        [family, family_member, workflow, waiting],
        [workflow_step, hidden_step],
    )


def epic_clan_agents(*, clan_summary: str | None = None) -> list[Agent]:
    generation = "20260717120000"

    def member(
        name: str,
        status: str,
        minute: int,
        *,
        stop_minute: int | None = None,
        model: str,
        provider: str,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-{name}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=datetime(2026, 7, 17, 12, minute, 0),
            run_start_time=datetime(2026, 7, 17, 12, minute, 0),
            stop_time=(
                datetime(2026, 7, 17, 12, stop_minute, 0)
                if stop_minute is not None
                else None
            ),
            raw_suffix=f"2026071712{minute:02d}00-{name}",
            agent_name=f"sase-6n.{name}",
            agent_clan="sase-6n",
            agent_clan_generation=generation,
            clan_summary=clan_summary if name == "phase-runtime" else None,
            agent_family_role="land" if name == "land" else "phase",
            tribe="epic",
            llm_provider=provider,
            model=model,
        )

    return sort_and_reorder(
        [
            member(
                "phase-runtime",
                "DONE",
                0,
                stop_minute=7,
                model="gpt-5",
                provider="codex",
            ),
            member(
                "phase-tui",
                "DONE",
                2,
                stop_minute=9,
                model="sonnet",
                provider="claude",
            ),
            member(
                "land",
                "RUNNING",
                9,
                model="gemini-pro",
                provider="gemini",
            ),
        ],
        [],
    )


def queued_clan_agents() -> list[Agent]:
    """Return a clan with one global-cap wait and one explicit barrier."""
    generation = "20260724120000"

    def waiter(
        name: str,
        minute: int,
        *,
        explicit: bool,
        threshold: int,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-{name}",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 24, 12, minute, 0),
            raw_suffix=f"2026072412{minute:02d}00-{name}",
            artifacts_dir=(
                f"/workspace/sase/artifacts/ace-run/2026072412{minute:02d}00-{name}"
            ),
            agent_name=f"queue-demo.{name}",
            agent_clan="queue-demo",
            agent_clan_generation=generation,
            tribe="epic",
            pid=4200 + minute,
            wait_runners=threshold,
            wait_runners_explicit=explicit,
            slot_requested_at=f"2026-07-24T12:{minute:02d}:00Z",
            llm_provider="codex",
            model="gpt-5",
        )

    return sort_and_reorder(
        [
            waiter("global-cap", 0, explicit=False, threshold=9),
            waiter("drain-barrier", 1, explicit=True, threshold=0),
        ],
        [],
    )


def decorate_clan_panel_sections(rows: list[Agent]) -> list[Agent]:
    """Give panel-only fixtures representative in-memory aggregate sections."""
    container = next(row for row in rows if row.is_clan_container)
    members = [container]
    for direct_member in container.runtime_children:
        members.append(direct_member)
        members.extend(
            row
            for row in rows
            if row.agent_clan is not None
            and row.tree_parent_key == direct_member.raw_suffix
        )
    assert len(members) >= 3
    for index, member in enumerate(members, start=1):
        member.output_variables = {
            "summary": f"member {index} complete\nfull visual detail",
        }
        member.workspace_num = index
    members[1].error_message = "Snapshot review found a rendering mismatch"
    members[1].error_traceback = "VisualDiffError: expected clan section glyph"
    members[1].step_output = {
        "meta_review": "check fold indicators\ninspect every level",
    }
    members[-1].activity = "integrating clan summary"
    return rows
