"""Agent-lane projection coverage for cleanup confirmation subjects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._confirmation_lanes import (
    AgentConfirmationSummary,
    _AgentConfirmationEntry,
    confirmation_lane_entries,
    confirmation_lane_summary,
    format_confirmation_entries,
)
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(
    name: str | None,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    workflow: str | None = None,
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    role_suffix: str | None = None,
    plan_chain_root: bool = False,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    status: str = "DONE",
    pid: int | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name or "unnamed-change",
        project_file="/tmp/projects/demo/demo.sase",
        status=status,
        start_time=datetime(2026, 7, 24, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        workflow=workflow,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type="agent" if parent_workflow else None,
        agent_family=agent_family,
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
        plan_chain_root=plan_chain_root,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
        pid=pid,
    )


def test_projection_dedupes_workflow_descendants_in_first_seen_lane_order() -> None:
    workflow = _agent(
        None,
        "workflow",
        agent_type=AgentType.WORKFLOW,
        workflow="release-flow",
        status="RUNNING",
        pid=10,
    )
    hidden_step = _agent(
        "internal.workflow.step.2",
        "step",
        parent_timestamp=workflow.raw_suffix,
        parent_workflow="release-flow",
        status="RUNNING",
        pid=11,
    )
    standalone = _agent("standalone", "standalone", status="RUNNING", pid=12)

    entries = confirmation_lane_entries(
        [hidden_step, standalone, workflow, hidden_step],
        [workflow, hidden_step, standalone],
        include_running_family_members=True,
    )

    assert entries == (
        _AgentConfirmationEntry("release-flow"),
        _AgentConfirmationEntry("standalone"),
    )
    assert format_confirmation_entries(entries) == [
        "  release-flow",
        "  standalone",
    ]


def test_sequential_family_uses_presented_lane_and_exact_running_member() -> None:
    root = _agent(
        "athena.feature--plan",
        "root",
        agent_family="athena.feature",
        agent_family_role="root",
        role_suffix="--plan",
    )
    member = _agent(
        "athena.feature--code",
        "member",
        parent_timestamp=root.raw_suffix,
        agent_family="athena.feature",
        role_suffix="--code",
        status="RUNNING",
        pid=42,
    )
    root.presented_agent_name = "buildbox.feature"
    root.presented_identity_name = "buildbox.feature--plan"
    member.presented_agent_name = "buildbox.feature--code"
    member.presented_identity_name = "buildbox.feature--code"

    entries = confirmation_lane_entries(
        [root, member],
        [root, member],
        include_running_family_members=True,
    )

    assert entries == (
        _AgentConfirmationEntry(
            "buildbox.feature",
            running_member_names=("buildbox.feature--code",),
        ),
    )
    assert format_confirmation_entries(entries) == [
        "  buildbox.feature @buildbox.feature--code"
    ]


def test_completed_family_members_never_leak_into_dismiss_entries() -> None:
    root = _agent(
        "family--plan",
        "root",
        agent_family="family",
        agent_family_role="root",
        role_suffix="--plan",
    )
    member = _agent(
        "family--code",
        "member",
        parent_timestamp=root.raw_suffix,
        agent_family="family",
        role_suffix="--code",
    )

    entries = confirmation_lane_entries([root, member], [root, member])

    assert entries == (_AgentConfirmationEntry("family"),)
    assert "family--plan" not in "\n".join(format_confirmation_entries(entries))
    assert "family--code" not in "\n".join(format_confirmation_entries(entries))


def test_rename_on_attach_family_root_uses_bare_family_lane() -> None:
    renamed_root = _agent(
        "review-lane--original",
        "root",
        agent_family="review-lane",
        agent_family_role="root",
        role_suffix="--original",
    )

    assert confirmation_lane_entries([renamed_root], [renamed_root]) == (
        _AgentConfirmationEntry("review-lane"),
    )


def test_plan_workflow_steps_resolve_to_family_lane() -> None:
    root = _agent(
        "plan-family--plan",
        "root",
        agent_type=AgentType.WORKFLOW,
        workflow="plan-workflow",
        agent_family="plan-family",
        agent_family_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
    )
    hidden_step = _agent(
        "hidden-planner-step",
        "step",
        parent_timestamp=root.raw_suffix,
        parent_workflow="plan-workflow",
    )

    assert confirmation_lane_entries([hidden_step], [root, hidden_step]) == (
        _AgentConfirmationEntry("plan-family"),
    )


def test_clan_descendants_resolve_to_direct_member_lanes_not_clan() -> None:
    family_root = _agent(
        "research.family--plan",
        "family-root",
        agent_family="research.family",
        agent_family_role="root",
        role_suffix="--plan",
        agent_clan="research",
        agent_clan_generation="generation",
    )
    family_member = _agent(
        "research.family--code",
        "family-member",
        parent_timestamp=family_root.raw_suffix,
        agent_family="research.family",
        role_suffix="--code",
        agent_clan="research",
        agent_clan_generation="generation",
    )
    direct_member = _agent(
        "research.solo",
        "solo",
        agent_clan="research",
        agent_clan_generation="generation",
    )
    loaded = project_clan_tree([family_root, family_member, direct_member])

    entries = confirmation_lane_entries(
        [family_member, direct_member],
        loaded,
    )

    assert entries == (
        _AgentConfirmationEntry("research.family"),
        _AgentConfirmationEntry("research.solo"),
    )
    assert all(entry.lane_name != "research" for entry in entries)


def test_missing_parent_uses_concrete_legacy_row_as_defensive_fallback() -> None:
    orphan = _agent(
        "legacy-orphan",
        "orphan",
        parent_timestamp="missing",
        parent_workflow="old-workflow",
    )

    assert confirmation_lane_entries([orphan], [orphan]) == (
        _AgentConfirmationEntry("legacy-orphan"),
    )


def test_summary_counts_family_lane_and_unique_concrete_agents() -> None:
    root = _agent(
        "release--plan",
        "root",
        agent_family="release",
        agent_family_role="root",
        role_suffix="--plan",
    )
    members = [
        _agent(
            f"release--phase-{index}",
            f"member-{index}",
            parent_timestamp=root.raw_suffix,
            agent_family="release",
            role_suffix=f"--phase-{index}",
        )
        for index in range(1, 4)
    ]
    targets = [root, *members, root]

    summary = confirmation_lane_summary(targets, targets)

    assert summary.agent_count == 4
    assert summary.lane_count == 1
    assert summary.subject_lines("Dismiss") == [
        "Dismiss: 1 lane · 4 agents",
        "  release",
    ]


def test_summary_counts_workflow_with_hidden_steps_as_one_lane() -> None:
    workflow = _agent(
        None,
        "workflow",
        agent_type=AgentType.WORKFLOW,
        workflow="release-flow",
    )
    hidden_steps = [
        _agent(
            f"internal-step-{index}",
            f"step-{index}",
            parent_timestamp=workflow.raw_suffix,
            parent_workflow="release-flow",
        )
        for index in range(2)
    ]
    targets = [workflow, *hidden_steps]

    summary = confirmation_lane_summary(targets, targets)

    assert summary.subject_lines("Dismiss") == [
        "Dismiss: 1 lane · 3 agents",
        "  release-flow",
    ]


def test_summary_omits_agent_detail_for_standalone_lanes() -> None:
    first = _agent("first", "first")
    second = _agent("second", "second")

    summary = confirmation_lane_summary([first, second], [first, second])

    assert summary.subject_lines("Kill") == [
        "Kill: 2 lanes",
        "  first",
        "  second",
    ]


def test_summary_subject_lines_use_singular_lane_and_agent_units() -> None:
    assert AgentConfirmationSummary(
        entries=(_AgentConfirmationEntry("first"),),
        agent_count=1,
    ).subject_lines("Kill") == ["Kill: 1 lane", "  first"]
    assert AgentConfirmationSummary(
        entries=(
            _AgentConfirmationEntry("first"),
            _AgentConfirmationEntry("second"),
        ),
        agent_count=1,
    ).subject_lines("Dismiss") == [
        "Dismiss: 2 lanes · 1 agent",
        "  first",
        "  second",
    ]


def test_summary_deduplicates_repeated_concrete_identity() -> None:
    first = _agent("standalone", "same-suffix")
    repeated_identity = _agent("standalone", "same-suffix")

    summary = confirmation_lane_summary(
        [first, repeated_identity, first],
        [first, repeated_identity],
    )

    assert summary.agent_count == 1
    assert summary.subject_lines("Dismiss") == [
        "Dismiss: 1 lane",
        "  standalone",
    ]


def test_empty_summary_emits_no_subject_lines() -> None:
    summary = confirmation_lane_summary([], [])

    assert summary.lane_count == 0
    assert summary.agent_count == 0
    assert summary.subject_lines("Dismiss") == []


def test_summary_headline_lane_count_equals_roster_length() -> None:
    root = _agent(
        "family--plan",
        "root",
        agent_family="family",
        agent_family_role="root",
        role_suffix="--plan",
    )
    member = _agent(
        "family--code",
        "member",
        parent_timestamp=root.raw_suffix,
        agent_family="family",
        role_suffix="--code",
    )
    standalone = _agent("standalone", "standalone")

    lines = confirmation_lane_summary(
        [root, member, standalone],
        [root, member, standalone],
    ).subject_lines("Dismiss")
    headline_count = int(lines[0].partition(": ")[2].partition(" ")[0])

    assert headline_count == len(lines[1:])


class _BulkConfirmationApp(AgentMarkingMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self.pushed: list[tuple[Any, Any]] = []

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def _do_bulk_kill_agents(
        self,
        killable: list[Agent],
        dismissable: list[Agent] | None = None,
    ) -> None:
        del killable, dismissable


def test_bulk_subject_can_show_same_family_lane_in_kill_and_dismiss_sections() -> None:
    completed_root = _agent(
        "release--plan",
        "root",
        agent_family="release",
        agent_family_role="root",
        role_suffix="--plan",
    )
    running_member = _agent(
        "release--code",
        "member",
        parent_timestamp=completed_root.raw_suffix,
        agent_family="release",
        role_suffix="--code",
        status="RUNNING",
        pid=91,
    )
    app = _BulkConfirmationApp([completed_root, running_member])

    app._present_bulk_kill_modal([running_member, completed_root])

    description = app.pushed[0][0].agent_description
    assert description == (
        "Kill: 1 lane\n  release @release--code\nDismiss: 1 lane\n  release"
    )
