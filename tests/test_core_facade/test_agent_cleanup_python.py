"""Tests for the Python agent cleanup planner."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_cleanup_facade import (
    _plan_agent_cleanup_python,
    agents_to_cleanup_targets,
)
from sase.core.agent_cleanup_wire import (
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_ALL_PANELS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TRIBE,
    KILL_KIND_RUNNING,
    KILL_KIND_WORKFLOW,
    SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY,
)

from tests.test_core_facade._agent_cleanup_helpers import (
    _agent,
    _id,
    _request,
    _SCENARIOS,
    _scenario_clan_scope,
    _scenario_clan_scope_active_parallel_family,
    _scenario_collapsed_group,
    _scenario_custom_child_running,
    _scenario_duplicate_child_inputs,
    _scenario_explicit_child_done,
    _scenario_explicit_child_running,
    _scenario_focused_panel_dismiss,
    _scenario_focused_panel_kill_dismiss,
    _scenario_marked_set,
    _scenario_pidless_dismiss_fallback,
    _scenario_parallel_family_root,
    _scenario_tribe_scope,
    _scenario_workflow_parent_with_children,
)


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_python_cleanup_planner_matches_legacy_partitions(scenario: Any) -> None:
    agents, request = scenario()
    plan = _plan_agent_cleanup_python(agents_to_cleanup_targets(agents), request)

    if scenario is _scenario_focused_panel_dismiss:
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]
        assert plan.kill_items == ()
    elif scenario is _scenario_focused_panel_kill_dismiss:
        assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]
        assert plan.counts.failed == 1
    elif scenario is _scenario_marked_set:
        assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]
    elif scenario is _scenario_collapsed_group:
        assert [item.identity.cl_name for item in plan.kill_items] == ["group-running"]
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["group-done"]
    elif scenario is _scenario_tribe_scope:
        assert [item.identity.cl_name for item in plan.kill_items] == ["alpha"]
        assert [item.reason for item in plan.skipped_items].count(
            "workflow_child_cascade_only"
        ) == 1
    elif scenario is _scenario_clan_scope:
        assert [item.identity.cl_name for item in plan.kill_items] == ["release"]
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["verified"]
        assert [item.cl_name for item in plan.cascaded_workflow_children] == [
            "release-step"
        ]
    elif scenario is _scenario_clan_scope_active_parallel_family:
        assert plan.kill_items == ()
        assert plan.dismiss_items == ()
        assert any(
            item.identity.cl_name == "family"
            and item.detail == "parallel family still active"
            for item in plan.skipped_items
        )
    elif scenario is _scenario_workflow_parent_with_children:
        assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
            ("workflow", KILL_KIND_WORKFLOW)
        ]
        assert [item.cl_name for item in plan.cascaded_workflow_children] == ["child"]
    elif scenario is _scenario_pidless_dismiss_fallback:
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["pidless"]
        assert plan.kill_items == ()
    elif scenario is _scenario_duplicate_child_inputs:
        assert [item.cl_name for item in plan.cascaded_workflow_children] == ["child"]
        assert [item.reason for item in plan.skipped_items].count(
            "workflow_child_cascade_only"
        ) == 2
    elif scenario is _scenario_explicit_child_running:
        assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
            ("child", KILL_KIND_RUNNING)
        ]
        assert plan.dismiss_items == ()
        assert plan.cascaded_workflow_children == ()
    elif scenario is _scenario_explicit_child_done:
        assert plan.kill_items == ()
        assert [item.identity.cl_name for item in plan.dismiss_items] == ["child"]
        assert plan.cascaded_workflow_children == ()
    elif scenario is _scenario_custom_child_running:
        assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
            ("child", KILL_KIND_RUNNING)
        ]
        assert plan.dismiss_items == ()
    elif scenario is _scenario_parallel_family_root:
        assert [item.identity.cl_name for item in plan.kill_items] == [
            "sase-6g",
            "sase-6g.1",
        ]


def test_python_cleanup_planner_side_effect_intents_for_workflow_dismissal() -> None:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="DONE",
        pid=None,
        raw_suffix="20260428100000",
        workflow="release",
        agent_name="root",
        artifacts_dir="/tmp/parent",
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="child",
        status="DONE",
        pid=None,
        raw_suffix="20260428100000_c0",
        workflow="release",
        parent_workflow="release",
        parent_timestamp="20260428100000",
        agent_name="root.plan",
        artifacts_dir="/tmp/child",
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=(_id(parent),),
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([parent, child]), request
    )

    assert [
        item.identity.cl_name for item in plan.side_effects.bundle_save_candidates
    ] == [
        "workflow",
        "child",
    ]
    assert [item.artifacts_dir for item in plan.side_effects.artifact_delete_paths] == [
        "/tmp/parent",
        "/tmp/child",
    ]
    assert [
        (item.cl_name, item.raw_suffix)
        for item in plan.side_effects.notification_dismiss_candidates
    ] == [
        ("workflow", "20260428100000"),
        ("child", "20260428100000_c0"),
    ]
    releases = plan.side_effects.workspace_release_requests
    assert len(releases) == 2
    assert releases[0].lookup_timestamp is True
    assert releases[0].artifacts_timestamp == "20260428100000"
    assert releases[1].lookup_timestamp is False


def test_python_cleanup_planner_side_effect_intents_for_bulk_kill() -> None:
    running = _agent(cl_name="running", status="RUNNING", pid=101, workspace_num=9)
    done = _agent(
        cl_name="done",
        status="DONE",
        pid=None,
        agent_name="done-name",
        raw_suffix="20260428110000",
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(running), _id(done)),
        include_pidless_as_dismissable=False,
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([running, done]), request
    )

    assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
    assert [item.cl_name for item in plan.side_effects.dismissed_index_additions] == [
        "done",
        "running",
    ]
    assert [
        item.workspace for item in plan.side_effects.workspace_release_requests
    ] == [None, 9]
    held = plan.side_effects.workspace_release_requests[0]
    assert held.lookup_timestamp is True
    assert held.artifacts_timestamp == "20260428110000"


def test_python_cleanup_planner_direct_child_side_effects_exclude_siblings() -> None:
    agents, request = _scenario_explicit_child_running()

    plan = _plan_agent_cleanup_python(agents_to_cleanup_targets(agents), request)

    assert [item.identity.cl_name for item in plan.kill_items] == ["child"]
    assert [item.cl_name for item in plan.side_effects.dismissed_index_additions] == [
        "child"
    ]
    assert [
        item.identity.cl_name for item in plan.side_effects.workspace_release_requests
    ] == ["child"]
    assert [
        item.identity.cl_name
        for item in plan.side_effects.notification_dismiss_candidates
    ] == ["child"]


def test_python_cleanup_planner_broad_scopes_keep_children_cascade_only() -> None:
    child = _agent(
        cl_name="child",
        raw_suffix="child-ts",
        pid=1002,
        parent_timestamp="parent-ts",
        tag="ops",
    )
    focused_request = _request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        focused_panel_tribe="ops",
    )
    tribe_request = _request(
        scope=CLEANUP_SCOPE_TRIBE,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        tribe="ops",
    )

    for request in (
        _request(
            scope=CLEANUP_SCOPE_ALL_PANELS,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
        ),
        focused_request,
        tribe_request,
    ):
        plan = _plan_agent_cleanup_python(agents_to_cleanup_targets([child]), request)

        assert plan.kill_items == ()
        assert plan.dismiss_items == ()
        assert [item.reason for item in plan.skipped_items] == [
            SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY
        ]


def test_python_cleanup_planner_clan_scope_without_generation_selects_all() -> None:
    current = _agent(
        cl_name="current",
        pid=101,
        agent_clan="research",
        agent_clan_generation="current-gen",
    )
    stale = _agent(
        cl_name="stale",
        pid=102,
        raw_suffix="stale-ts",
        agent_clan="research",
        agent_clan_generation="stale-gen",
    )
    request = _request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        clan_name="research",
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([current, stale]), request
    )

    assert [item.identity.cl_name for item in plan.kill_items] == [
        "current",
        "stale",
    ]


def test_python_cleanup_planner_direct_workflow_child_keeps_parent_workspace() -> None:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="RUNNING",
        pid=1001,
        raw_suffix="parent-ts",
        workflow="release",
        workspace_num=1,
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="child",
        status="RUNNING",
        pid=1002,
        raw_suffix="child-ts",
        workflow="release",
        parent_workflow="release",
        parent_timestamp="parent-ts",
        workspace_num=2,
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(child),),
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([parent, child]), request
    )

    assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
        ("child", KILL_KIND_WORKFLOW)
    ]
    assert [item.cl_name for item in plan.side_effects.dismissed_index_additions] == [
        "child"
    ]
    assert plan.side_effects.workspace_release_requests == ()


def test_python_cleanup_planner_treats_stopped_as_dismissable() -> None:
    stopped = _agent(cl_name="stopped", status="STOPPED", pid=None)
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(stopped),),
    )

    plan = _plan_agent_cleanup_python(agents_to_cleanup_targets([stopped]), request)

    assert plan.kill_items == ()
    assert [item.identity.cl_name for item in plan.dismiss_items] == ["stopped"]


def test_python_cleanup_planner_cascades_parallel_root_kill_only_to_members() -> None:
    root = _agent(
        cl_name="sase-6g",
        raw_suffix="root-ts",
        pid=100,
        agent_family_parallel=True,
    )
    member_one = _agent(
        cl_name="sase-6g.1",
        raw_suffix="member-one-ts",
        parent_timestamp="root-ts",
        pid=101,
        agent_family_parallel=True,
    )
    member_two = _agent(
        cl_name="sase-6g.2",
        raw_suffix="member-two-ts",
        parent_timestamp="root-ts",
        pid=102,
        agent_family_parallel=True,
    )
    serial_child = _agent(
        cl_name="sase-6g--code",
        raw_suffix="serial-ts",
        parent_timestamp="root-ts",
        pid=103,
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(root),),
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([root, member_one, member_two, serial_child]),
        request,
    )

    assert [item.identity.cl_name for item in plan.kill_items] == [
        "sase-6g",
        "sase-6g.1",
        "sase-6g.2",
    ]
    assert [item.cl_name for item in plan.side_effects.dismissed_index_additions] == [
        "sase-6g",
        "sase-6g.1",
        "sase-6g.2",
    ]


def test_python_cleanup_planner_parallel_member_kill_does_not_cascade() -> None:
    root = _agent(
        cl_name="sase-6g",
        raw_suffix="root-ts",
        pid=100,
        agent_family_parallel=True,
    )
    selected = _agent(
        cl_name="sase-6g.1",
        raw_suffix="member-one-ts",
        parent_timestamp="root-ts",
        pid=101,
        agent_family_parallel=True,
    )
    sibling = _agent(
        cl_name="sase-6g.2",
        raw_suffix="member-two-ts",
        parent_timestamp="root-ts",
        pid=102,
        agent_family_parallel=True,
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(selected),),
    )

    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([root, selected, sibling]),
        request,
    )

    assert [item.identity.cl_name for item in plan.kill_items] == ["sase-6g.1"]


def test_python_cleanup_planner_gates_parallel_root_dismissal_until_done() -> None:
    root = _agent(
        cl_name="root",
        raw_suffix="root-ts",
        status="DONE",
        pid=None,
        agent_family_parallel=True,
    )
    member = _agent(
        cl_name="member",
        raw_suffix="member-ts",
        parent_timestamp="root-ts",
        status="RUNNING",
        pid=101,
        agent_family_parallel=True,
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=(_id(root),),
    )

    active_plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([root, member]),
        request,
    )
    assert active_plan.dismiss_items == ()
    assert any(
        item.identity.cl_name == "root"
        and item.detail == "parallel family still active"
        for item in active_plan.skipped_items
    )

    member.status = "DONE"
    member.pid = None
    finished_plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets([root, member]),
        request,
    )
    assert [item.identity.cl_name for item in finished_plan.dismiss_items] == [
        "root",
        "member",
    ]
