"""Family scopes for Enter-on-agent: containers, members, and ordering."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from sase.ace.tui.actions.agents._agent_enter_targets import (
    build_gate_notification_index,
    enter_action_label_for_targets,
    resolve_agent_enter_targets,
)
from sase.ace.tui.actions.agents._patch_navigation import (
    AgentPatchNavigationMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType

from ._agent_enter_targets_helpers import (
    _family,
    _gate_row,
    _matching_action_data,
    _notification,
    _resolve,
    _sources,
    _summary_lookup,
)
from ._agent_unread_helpers import make_agent


def test_container_collects_member_gate_rows() -> None:
    gate = _gate_row("010101", notification_id="n-gate")
    member = make_agent(name="worker", raw_suffix="20260918010202")
    root = _family(members=[member, gate])
    resolution = _resolve(root)
    kinds = _sources(resolution)
    assert "gate_row" in kinds
    assert resolution.targets[0].source == "gate_row"
    assert resolution.targets[-1].source == "patch"


def test_container_matches_member_identity_notifications() -> None:
    member = make_agent(name="worker", raw_suffix="20260918010202")
    root = _family(members=[member])
    notification = _notification(
        "n-plan",
        "PlanApproval",
        action_data=_matching_action_data(member),
        files=["/tmp/plans/review_plan_enter_keymap.md"],
    )
    resolution = _resolve(root, [notification])
    assert [t.key for t in resolution.targets] == ["gate:n-plan", "patch:fam-root"]
    [gate_target, _] = resolution.targets
    assert gate_target.label == "Review plan"
    assert gate_target.detail == "review_plan_enter_keymap.md"


def test_member_creator_back_reference_matches() -> None:
    member = replace(
        make_agent(name="worker", raw_suffix="20260918010202"),
        gate_id="gate-creator-1",
    )
    assert member.is_gate is False
    gate = _gate_row("010101", gate_id="gate-creator-1")
    member = replace(member, followup_agents=[gate])
    root = _family(members=[member])
    gate.family_container = root
    resolution = _resolve(member)
    assert [t.key for t in resolution.targets] == [
        "gate:gate-creator-1",
        "patch:worker",
    ]


def test_member_gate_creator_agent_matches() -> None:
    member = replace(
        make_agent(name="worker", raw_suffix="20260918010202"),
        agent_name="creator-agent",
    )
    gate = replace(
        _gate_row("010101", gate_id="gate-other-1"),
        gate_creator_agent="creator-agent",
    )
    member = replace(member, followup_agents=[gate])
    root = _family(members=[member])
    gate.family_container = root
    resolution = _resolve(member)
    assert resolution.targets[0].key == "gate:gate-other-1"


def test_row_backed_target_wins_over_notification_duplicate() -> None:
    agent = _gate_row(
        "010101",
        notification_id="n-dup",
        bundle_path="/tmp/bundles/gate-abc123",
    )
    notification = _notification(
        "n-dup",
        "SudoRequest",
        action_data={
            **_matching_action_data(agent),
            "bundle_path": "/tmp/bundles/gate-abc123",
        },
    )
    resolution = _resolve(agent, [notification])
    assert len(resolution.targets) == 1
    assert resolution.targets[0].source == "gate_row"


def test_settled_bundle_drops_notification_only_target() -> None:
    # A notification-only target whose bundle belongs to a settled gate row
    # in the roster is dropped.
    member = make_agent(name="worker", raw_suffix="20260918010303")
    settled_gate = _gate_row(
        "040404",
        gate_id="gate-settled",
        state="answered",
        stop_time=datetime(2026, 9, 18, 13, 0, 0),
        bundle_path="/tmp/bundles/gate-settled",
    )
    root = _family(members=[member, settled_gate], root_cl="~")
    stale = _notification(
        "n-stale",
        "CustomGate",
        action_data={
            **_matching_action_data(member),
            "bundle_path": "/tmp/bundles/gate-settled",
        },
    )
    resolution = _resolve(root, [stale])
    assert "notification" not in _sources(resolution)


def test_old_plan_approval_found_behind_newer_notifications() -> None:
    agent = replace(
        make_agent(name="target", status="PLAN", raw_suffix="20260918010101"),
        agent_name="target-agent",
    )
    newer = [
        _notification(
            f"newer-{index}", "JumpToPatch", timestamp="2026-09-19T12:00:00+00:00"
        )
        for index in range(120)
    ]
    old = _notification(
        "old-match",
        "PlanApproval",
        timestamp="2026-09-18T12:00:00+00:00",
        action_data=_matching_action_data(agent),
    )
    resolution = _resolve(agent, [*newer, old])
    assert "gate:old-match" in [t.key for t in resolution.targets]


def test_container_falls_back_to_newest_member_patch() -> None:
    member = make_agent(name="member-patch", raw_suffix="20260918010202")
    gate = _gate_row("010101")
    root = _family(members=[member, gate], root_cl="~")
    resolution = _resolve(root)
    assert resolution.targets[-1].key == "patch:member-patch"
    assert resolution.targets[-1].project_file == member.project_file


def test_project_level_plan_family_container_resolves_gate_only() -> None:
    """Enter on a project-level plan family goes straight to its gate.

    The concrete planner step is a workflow step child of a project-level
    workflow, so the real Patch resolver must map it to None (not the
    project name); otherwise the container would also gain a phantom
    ``Go to Patch`` target and Enter would show a chooser.
    """
    suffix = "20260918010101"
    workflow = "tmp_plan"
    container = replace(
        make_agent(name="demo", raw_suffix=suffix),
        agent_type=AgentType.WORKFLOW,
        workflow=workflow,
        agent_family_role="root",
        agent_family="fam",
        agent_name="starter",
        plan_chain_root=True,
    )
    assert container.is_project_agent
    planner = replace(
        make_agent(name="run_agent", raw_suffix="20260918010202"),
        agent_type=AgentType.WORKFLOW,
        workflow=workflow,
        parent_workflow=workflow,
        parent_timestamp=suffix,
        step_type="agent",
    )
    gate = _gate_row("010101", kind="plan", start_status="TALE")
    container = replace(container, runtime_children=[planner], followup_agents=[gate])
    planner.family_container = container
    gate.family_container = container

    class _PatchApp(AgentPatchNavigationMixin):
        _agents_with_children: list[Agent] = []

    app = _PatchApp()
    app._agents_with_children = [container, planner, gate]
    # The planner step reaches the roster through the workflow-child branch.
    assert app._resolve_agent_cl_name(planner) is None

    index = build_gate_notification_index([])
    resolution = resolve_agent_enter_targets(
        container,
        gate_notifications=index,
        patch_name_for=app._resolve_agent_cl_name,
        patch_lookup=_summary_lookup,
    )
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.kind == "gate"
    assert target.label == "Review tale plan"
    assert enter_action_label_for_targets(resolution.targets) != "choose action"


def test_ordering_gates_newest_first_patch_last() -> None:
    old_gate = _gate_row(
        "010101",
        gate_id="gate-old",
        start_time=datetime(2026, 9, 18, 10, 0, 0),
    )
    new_gate = _gate_row(
        "020202",
        gate_id="gate-new",
        kind="launch",
        start_status="LAUNCH",
        start_time=datetime(2026, 9, 18, 12, 0, 0),
    )
    root = _family(members=[old_gate, new_gate])
    resolution = _resolve(root)
    assert [t.key for t in resolution.targets] == [
        "gate:gate-new",
        "gate:gate-old",
        "patch:fam-root",
    ]
    assert resolution.primary is not None
    assert resolution.primary.key == "gate:gate-new"
    assert resolution.primary.label == "Approve agent launch"
