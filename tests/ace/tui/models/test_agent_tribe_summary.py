"""Pure tribe-panel summary projection tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
    _tribe_panel_identity,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

_NOW = datetime(2026, 7, 18, 15, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    start_minute: int,
    clan: str | None = None,
    generation: str | None = None,
    family: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> Agent:
    start = datetime(2026, 7, 18, 14, start_minute, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=start,
        run_start_time=start,
        stop_time=_NOW if status in {"DONE", "FAILED"} else None,
        raw_suffix=f"suffix-{name}",
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation=generation,
        agent_family=family,
        agent_family_role="root" if role == "plan" else role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
        parent_timestamp=parent,
        model="gpt-5",
    )


def _mixed_roots() -> tuple[list[Agent], dict[str, Agent]]:
    clan_member = _agent(
        "research.failed",
        "FAILED",
        start_minute=0,
        clan="research",
        generation="gen-1",
    )
    clan_member.error_message = "Build failed\nfull diagnostic"
    clan_member.output_variables = {
        "report": {
            "passed": True,
            "files": ["a.py", "b.py"],
        }
    }
    clan_container = project_clan_tree([clan_member])[0]

    family_root = _agent(
        "build--plan",
        "RUNNING",
        start_minute=5,
        family="build",
        role="plan",
    )
    family_child = _agent(
        "build--code",
        "WAITING",
        start_minute=10,
        family="build",
        role="code",
        parent=family_root.raw_suffix,
    )
    family_child.activity = "waiting on review"
    family_root.followup_agents = [family_child]

    standalone = _agent("standalone", "DONE", start_minute=20)
    standalone.step_output = {"meta_release_notes": "ready\nfull notes"}
    return [clan_container, family_root, family_child, standalone], {
        "clan": clan_container,
        "clan_member": clan_member,
        "family": family_root,
        "family_child": family_child,
        "standalone": standalone,
    }


def test_snapshot_preserves_mixed_unit_order_and_aggregates_loaded_rows() -> None:
    roots, rows = _mixed_roots()

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        roots,
        panel_collapsed=True,
        unread_ids={rows["standalone"].identity},
        marked_ids={rows["family_child"].identity},
        now=_NOW,
    )

    assert snapshot.container_identity == _tribe_panel_identity("epic")
    assert snapshot.label == "▲ @epic"
    assert snapshot.panel_collapsed is True
    assert [unit.kind for unit in snapshot.units] == ["clan", "family", "agent"]
    assert [unit.label for unit in snapshot.units] == [
        "research",
        "build",
        "standalone",
    ]
    assert snapshot.clan_count == 1
    assert snapshot.family_count == 1
    assert snapshot.lane_count == 3
    assert snapshot.nested_count == 2
    assert snapshot.runtime_span == "1h"
    assert snapshot.counts.failed == 1
    assert snapshot.counts.running == 1
    assert snapshot.counts.unread == 1
    assert snapshot.units[1].is_marked is True
    assert snapshot.units[2].is_unread is True
    assert [child.label for child in snapshot.units[1].children] == ["--code"]
    assert [entry.preview for entry in snapshot.errors] == ["Build failed"]
    assert [entry.name for entry in snapshot.output_variables] == ["report"]
    assert snapshot.output_variables[0].value == {
        "passed": True,
        "files": ["a.py", "b.py"],
    }
    assert [entry.name for entry in snapshot.workflow_variables] == ["Release Notes"]


def test_attention_digest_and_default_identity_use_unit_statuses() -> None:
    roots, _rows = _mixed_roots()
    snapshot = build_agent_tribe_summary_snapshot(
        None,
        roots,
        panel_collapsed=False,
        now=_NOW,
    )

    assert snapshot.label == "⌂ @default"
    assert snapshot.container_identity == ("panel", None)
    assert snapshot.panel_collapsed is False
    assert [(entry.unit_label, entry.preview) for entry in snapshot.attention] == [
        ("research", "Build failed")
    ]


def test_family_unit_counts_and_children_use_concrete_planner_projection() -> None:
    root = _agent(
        "build--plan",
        "WORKING TALE",
        start_minute=0,
        family="build",
        role="plan",
    )
    planner = _agent(
        "build--plan-step",
        "TALE APPROVED",
        start_minute=0,
        family="build",
        role="plan",
        parent=root.raw_suffix,
    )
    planner.agent_family_role = "plan"
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    planner.model = "claude/opus"
    coder = _agent(
        "build--code",
        "WORKING TALE",
        start_minute=10,
        family="build",
        role="code",
        parent=root.raw_suffix,
    )
    coder.model = "codex/gpt-5"
    root.runtime_children = [planner, coder]
    root.followup_agents = [coder]

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        [root, planner, coder],
        panel_collapsed=True,
        now=_NOW,
    )

    family = snapshot.units[0]
    assert family.identity == root.identity
    assert family.status == "WORKING TALE"
    assert [child.identity for child in family.children] == [
        planner.identity,
        coder.identity,
    ]
    assert [child.status for child in family.children] == [
        "TALE APPROVED",
        "WORKING TALE",
    ]
    assert [child.model for child in family.children] == [
        "claude/opus",
        "codex/gpt-5",
    ]
    assert family.status_counts is not None
    assert family.status_counts.running == 1
    assert family.status_counts.done == 1
    assert [child.effective_bucket for child in family.children] == [
        "Done",
        "Running",
    ]
    assert snapshot.lane_count == 1
    assert snapshot.nested_count == 2


def test_tribe_queue_count_is_scoped_and_aggregate_is_queued() -> None:
    implicit = _agent(
        "research.implicit",
        "WAITING",
        start_minute=0,
        clan="research",
        generation="gen-1",
    )
    explicit = _agent(
        "research.explicit",
        "WAITING",
        start_minute=1,
        clan="research",
        generation="gen-1",
    )
    dependency = _agent(
        "research.dependency",
        "WAITING",
        start_minute=2,
        clan="research",
        generation="gen-1",
    )
    for agent in (implicit, explicit, dependency):
        agent.pid = 100
    implicit.wait_runners = 9
    implicit.slot_requested_at = "2026-07-18T14:00:00Z"
    explicit.wait_runners = 0
    explicit.wait_runners_explicit = True
    explicit.slot_requested_at = "2026-07-18T14:00:01Z"
    dependency.waiting_for = ["research.other"]
    refresh_runner_slot_context([implicit, explicit, dependency], effective_limit=10)
    projected = project_clan_tree([implicit, explicit, dependency])

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        projected,
        panel_collapsed=True,
        now=_NOW,
    )
    unrelated_dependency = _agent(
        "review.dependency",
        "WAITING",
        start_minute=3,
    )
    unrelated_dependency.waiting_for = ["review.other"]
    unrelated = build_agent_tribe_summary_snapshot(
        "review",
        [unrelated_dependency],
        panel_collapsed=True,
        now=_NOW,
    )

    assert (snapshot.counts.queued, snapshot.counts.waiting) == (2, 1)
    assert snapshot.status == "QUEUED"
    assert snapshot.units[0].status == "QUEUED"
    assert snapshot.attention == ()
    assert snapshot.units[0].status_counts is not None
    assert (
        snapshot.units[0].status_counts.queued,
        snapshot.units[0].status_counts.waiting,
    ) == (2, 1)
    assert (unrelated.counts.queued, unrelated.counts.waiting) == (0, 1)


def test_workflow_unit_counts_agent_steps_once_and_never_as_nested() -> None:
    root = _agent("workflow", "DONE", start_minute=0)
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    main = _agent("workflow-main", "DONE", start_minute=1)
    main.parent_timestamp = root.raw_suffix
    main.parent_workflow = "demo"
    main.step_type = "agent"
    python_step = _agent("workflow-python", "DONE", start_minute=2)
    python_step.parent_timestamp = root.raw_suffix
    python_step.parent_workflow = "demo"
    python_step.step_type = "python"
    root.runtime_children = [main, python_step]

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        [root, main, python_step],
        panel_collapsed=True,
        now=_NOW,
    )

    assert snapshot.lane_count == 1
    assert snapshot.nested_count == 0
    assert snapshot.counts.done == 1
    assert [child.identity for child in snapshot.units[0].children] == [
        main.identity,
        python_step.identity,
    ]


def test_finished_family_projects_all_members_to_done() -> None:
    planner = _agent(
        "build--plan",
        "TALE DONE",
        start_minute=0,
        family="build",
        role="plan",
    )
    coder = _agent(
        "build--code",
        "TALE DONE",
        start_minute=10,
        family="build",
        role="code",
        parent=planner.raw_suffix,
    )
    planner.followup_agents = [coder]

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        [planner, coder],
        panel_collapsed=True,
        now=_NOW,
    )

    family = snapshot.units[0]
    assert family.status_counts is not None
    assert family.status_counts.running == 0
    assert family.status_counts.done == 2
    assert snapshot.counts.running == 0
    assert snapshot.counts.done == 1
    assert snapshot.lane_count == 1
    assert snapshot.nested_count == 1


def test_machine_qualified_children_compact_against_presented_containers() -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    local_clan_member = _agent(
        "athena.research.worker",
        "DONE",
        start_minute=0,
        clan="athena.research",
        generation="local",
    )
    foreign_clan_member = _agent(
        "zeus.review.peer",
        "DONE",
        start_minute=1,
        clan="zeus.review",
        generation="foreign",
    )
    family_root = _agent(
        "athena.build--plan",
        "RUNNING",
        start_minute=2,
        family="athena.build",
        role="plan",
    )
    family_child = _agent(
        "athena.build--code",
        "WAITING",
        start_minute=3,
        family="athena.build",
        role="code",
        parent=family_root.raw_suffix,
    )
    family_root.followup_agents = [family_child]

    projected = project_clan_tree(
        [local_clan_member, foreign_clan_member, family_root, family_child]
    )
    for agent in projected:
        agent.refresh_presented_agent_name(identity)

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        projected,
        panel_collapsed=True,
        now=_NOW,
    )

    units = {unit.label: unit for unit in snapshot.units}
    assert [child.label for child in units["research"].children] == [".worker"]
    assert [child.label for child in units["build"].children] == ["--code"]
    assert "zeus.review" in units
    assert [child.label for child in units["zeus.review"].children] == [".peer"]


def test_local_machine_clan_with_family_projects_to_one_presented_unit() -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    family_root = _agent(
        "athena.sase-8t.1--plan",
        "RUNNING",
        start_minute=0,
        clan="athena.sase-8t",
        generation="gen",
        family="athena.sase-8t.1",
        role="plan",
    )
    agents = [
        family_root,
        _agent(
            "athena.sase-8t.2",
            "WAITING",
            start_minute=1,
            clan="athena.sase-8t",
            generation="gen",
        ),
        _agent(
            "athena.sase-8t.land",
            "WAITING",
            start_minute=2,
            clan="athena.sase-8t",
            generation="gen",
        ),
    ]
    foreign_family_root = _agent(
        "zeus.review.1--plan",
        "RUNNING",
        start_minute=3,
        clan="zeus.review",
        generation="foreign",
        family="zeus.review.1",
        role="plan",
    )

    for agent in (*agents, foreign_family_root):
        agent.refresh_presented_agent_name(identity)

    assert family_root.presented_clan_reference_name() == "sase-8t"
    assert foreign_family_root.presented_clan_reference_name() == "zeus.review"

    projected = project_clan_tree(agents)
    containers = [agent for agent in projected if agent.is_clan_container]
    assert len(containers) == 1
    assert containers[0].presented_clan_reference_name() == "sase-8t"

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        projected,
        panel_collapsed=True,
        now=_NOW,
    )

    assert [unit.label for unit in snapshot.units] == ["sase-8t"]


def test_reference_tribe_counts_six_lane_statuses_and_eight_nested() -> None:
    agents: list[Agent] = []
    for index in range(4):
        root = _agent(
            f"family-{index}--plan",
            "WORKING TALE" if index < 2 else "TALE DONE",
            start_minute=index * 5,
            family=f"family-{index}",
            role="plan",
        )
        planner = _agent(
            f"family-{index}--plan-step",
            "TALE APPROVED",
            start_minute=index * 5,
            family=f"family-{index}",
            role="plan",
            parent=root.raw_suffix,
        )
        planner.agent_family_role = "plan"
        planner.parent_workflow = "ace-run"
        planner.step_type = "agent"
        coder = _agent(
            f"family-{index}--code",
            "WORKING TALE" if index < 2 else "TALE DONE",
            start_minute=index * 5 + 1,
            family=f"family-{index}",
            role="code",
            parent=root.raw_suffix,
        )
        root.runtime_children = [planner, coder]
        root.followup_agents = [coder]
        agents.extend((root, planner, coder))

    for index in range(2):
        root = _agent(f"workflow-{index}", "DONE", start_minute=30 + index * 2)
        root.agent_type = AgentType.WORKFLOW
        root.workflow = f"workflow-{index}"
        main = _agent(
            f"workflow-{index}-main",
            "DONE",
            start_minute=31 + index * 2,
        )
        main.parent_timestamp = root.raw_suffix
        main.parent_workflow = root.workflow
        main.step_type = "agent"
        root.runtime_children = [main]
        agents.extend((root, main))

    snapshot = build_agent_tribe_summary_snapshot(
        None,
        agents,
        panel_collapsed=True,
        now=_NOW,
    )

    assert snapshot.family_count == 4
    assert snapshot.lane_count == 6
    assert snapshot.nested_count == 8
    assert snapshot.counts.running == 2
    assert snapshot.counts.done == 4
