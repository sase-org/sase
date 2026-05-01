"""Tests for the agent cleanup planning facade."""

from __future__ import annotations

import sys
import types
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_cleanup_facade import (
    agent_to_cleanup_target,
    agents_to_cleanup_targets,
    plan_agent_cleanup,
    plan_agent_cleanup_python,
)
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_GROUP,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TAG,
    KILL_KIND_RUNNING,
    KILL_KIND_WORKFLOW,
    AgentCleanupIdentityWire,
    AgentCleanupRequestWire,
    agent_cleanup_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


_START = datetime(2026, 4, 30, 9, 0, 0)
_STOP = datetime(2026, 4, 30, 9, 5, 0)


def _agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "cl",
    status: str = "RUNNING",
    pid: int | None = 123,
    raw_suffix: str | None = "20260430090000",
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    tag: str | None = None,
    agent_name: str | None = None,
    role_suffix: str | None = None,
    plan_chain_parent_timestamp: str | None = None,
    workspace_num: int | None = 7,
    artifacts_dir: str | None = "/tmp/artifacts",
    start_time: datetime | None = _START,
    stop_time: datetime | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/project.gp",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        workspace_num=workspace_num,
        workflow=workflow,
        pid=pid,
        raw_suffix=raw_suffix,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        tag=tag,
        agent_name=agent_name,
        role_suffix=role_suffix,
        plan_chain_parent_timestamp=plan_chain_parent_timestamp,
        artifacts_dir=artifacts_dir,
    )


def _id(agent: Agent) -> AgentCleanupIdentityWire:
    return AgentCleanupIdentityWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
    )


def _request(
    *,
    scope: str,
    mode: str,
    focused_panel_tag: str | None = None,
    tag: str | None = None,
    identities: tuple[AgentCleanupIdentityWire, ...] = (),
    include_pidless_as_dismissable: bool = False,
) -> AgentCleanupRequestWire:
    return AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=scope,
        mode=mode,
        focused_panel_tag=focused_panel_tag,
        tag=tag,
        identities=identities,
        include_pidless_as_dismissable=include_pidless_as_dismissable,
    )


def _scenario_focused_panel_dismiss() -> tuple[list[Agent], AgentCleanupRequestWire]:
    done = _agent(cl_name="done", status="DONE", pid=None, tag="focus")
    running = _agent(cl_name="running", status="RUNNING", pid=101, tag="focus")
    other = _agent(cl_name="other", status="DONE", pid=None, tag="other")
    return [
        done,
        running,
        other,
    ], _request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        focused_panel_tag="focus",
    )


def _scenario_focused_panel_kill_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    running = _agent(cl_name="running", status="RUNNING", pid=101, tag=None)
    done = _agent(cl_name="done", status="FAILED", pid=None, tag=None, stop_time=_STOP)
    other = _agent(cl_name="other", status="DONE", pid=None, tag="other")
    return [
        running,
        done,
        other,
    ], _request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        focused_panel_tag=None,
    )


def _scenario_marked_set() -> tuple[list[Agent], AgentCleanupRequestWire]:
    running = _agent(cl_name="running", status="RUNNING", pid=101)
    done = _agent(cl_name="done", status="DONE", pid=None)
    unmarked = _agent(cl_name="unmarked", status="RUNNING", pid=202)
    return [
        running,
        done,
        unmarked,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(running), _id(done)),
    )


def _scenario_collapsed_group() -> tuple[list[Agent], AgentCleanupRequestWire]:
    running = _agent(cl_name="group-running", status="RUNNING", pid=101)
    done = _agent(cl_name="group-done", status="DONE", pid=None)
    outside = _agent(cl_name="outside", status="RUNNING", pid=202)
    return [
        running,
        done,
        outside,
    ], _request(
        scope=CLEANUP_SCOPE_FOCUSED_GROUP,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(running), _id(done)),
    )


def _scenario_tag_scope() -> tuple[list[Agent], AgentCleanupRequestWire]:
    alpha = _agent(
        cl_name="alpha",
        status="RUNNING",
        pid=101,
        raw_suffix="alpha-ts",
        tag="alpha",
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="alpha-child",
        status="RUNNING",
        pid=102,
        raw_suffix="child",
        workflow="deploy",
        parent_workflow=alpha.workflow,
        parent_timestamp=alpha.raw_suffix,
        tag=None,
    )
    beta = _agent(
        cl_name="beta",
        status="RUNNING",
        pid=201,
        raw_suffix="beta-ts",
        tag="beta",
    )
    return [
        alpha,
        child,
        beta,
    ], _request(
        scope=CLEANUP_SCOPE_TAG,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        tag="alpha",
    )


def _scenario_workflow_parent_with_children() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="RUNNING",
        pid=1001,
        raw_suffix="parent-ts",
        workflow="release",
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
    )
    return [
        parent,
        child,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(parent),),
    )


def _scenario_pidless_dismiss_fallback() -> tuple[list[Agent], AgentCleanupRequestWire]:
    pidless = _agent(cl_name="pidless", status="RUNNING", pid=None)
    return [
        pidless,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(pidless),),
        include_pidless_as_dismissable=True,
    )


def _scenario_duplicate_child_inputs() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="RUNNING",
        pid=1001,
        raw_suffix="parent-ts",
        workflow="release",
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
    )
    duplicate_child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="child",
        status="RUNNING",
        pid=1002,
        raw_suffix="child-ts",
        workflow="release",
        parent_workflow="release",
        parent_timestamp="parent-ts",
    )
    return [
        parent,
        child,
        duplicate_child,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(parent), _id(child)),
    )


_SCENARIOS = [
    pytest.param(_scenario_focused_panel_dismiss, id="focused-panel-dismiss-done"),
    pytest.param(
        _scenario_focused_panel_kill_dismiss,
        id="focused-panel-kill-dismiss",
    ),
    pytest.param(_scenario_marked_set, id="marked-set"),
    pytest.param(_scenario_collapsed_group, id="collapsed-group"),
    pytest.param(_scenario_tag_scope, id="tag-scope"),
    pytest.param(
        _scenario_workflow_parent_with_children,
        id="workflow-parent-cascade",
    ),
    pytest.param(_scenario_pidless_dismiss_fallback, id="pidless-dismiss-fallback"),
    pytest.param(_scenario_duplicate_child_inputs, id="duplicate-child-inputs"),
]


def test_agent_to_cleanup_target_converts_current_agent_shape() -> None:
    agent = _agent(
        cl_name="convert",
        status="FAILED",
        pid=None,
        raw_suffix="20260430090102",
        tag="triage",
        agent_name="friendly",
        stop_time=_STOP,
    )

    target = agent_to_cleanup_target(agent)

    assert target.identity == AgentCleanupIdentityWire(
        agent_type="run",
        cl_name="convert",
        raw_suffix="20260430090102",
    )
    assert target.status == "FAILED"
    assert target.workspace == 7
    assert target.from_changespec is False
    assert target.tag == "triage"
    assert target.agent_name == "friendly"
    assert target.display_name == "convert"
    assert target.start_time == "2026-04-30T09:00:00"
    assert target.stop_time == "2026-04-30T09:05:00"


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_python_cleanup_planner_matches_legacy_partitions(scenario: Any) -> None:
    agents, request = scenario()
    plan = plan_agent_cleanup_python(agents_to_cleanup_targets(agents), request)

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
    elif scenario is _scenario_tag_scope:
        assert [item.identity.cl_name for item in plan.kill_items] == ["alpha"]
        assert [item.reason for item in plan.skipped_items].count(
            "workflow_child_cascade_only"
        ) == 1
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

    plan = plan_agent_cleanup_python(
        agents_to_cleanup_targets([parent, child]), request
    )

    assert [
        intent.new_name for intent in plan.side_effects.dismissal_rename_allocations
    ] == ["260430.root", "260430.root.plan"]
    assert dict(plan.side_effects.wait_reference_rewrite_map) == {
        "root": "260430.root",
        "root.plan": "260430.root.plan",
    }
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


def test_cleanup_planner_treats_plan_chain_phase_as_selectable_row() -> None:
    phase = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="phase",
        status="DONE",
        pid=None,
        raw_suffix="20260428101010",
        workflow="plan",
        parent_timestamp="20260428100000",
        plan_chain_parent_timestamp="20260428100000",
        role_suffix=".coder",
        agent_name="a.coder",
        artifacts_dir="/tmp/coder",
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=(_id(phase),),
    )

    target = agent_to_cleanup_target(phase)
    plan = plan_agent_cleanup_python((target,), request)

    assert target.is_workflow_child is False
    assert [item.identity.cl_name for item in plan.dismiss_items] == ["phase"]
    assert plan.skipped_items == ()
    assert [item.artifacts_dir for item in plan.side_effects.artifact_delete_paths] == [
        "/tmp/coder"
    ]


def test_cleanup_planner_root_dismiss_cascades_plan_chain_phases() -> None:
    root = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="root",
        status="DONE",
        pid=None,
        raw_suffix="20260428100000",
        workflow="plan",
        role_suffix=".plan",
        agent_name="a.plan",
        artifacts_dir="/tmp/plan",
    )
    phase = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="phase",
        status="DONE",
        pid=None,
        raw_suffix="20260428101010",
        workflow="plan",
        parent_timestamp="20260428100000",
        plan_chain_parent_timestamp="20260428100000",
        role_suffix=".coder",
        agent_name="a.coder",
        artifacts_dir="/tmp/coder",
    )
    request = _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=(_id(root),),
    )

    plan = plan_agent_cleanup_python(agents_to_cleanup_targets([root, phase]), request)

    assert [item.identity.cl_name for item in plan.dismiss_items] == ["root"]
    assert [
        item.identity.cl_name for item in plan.side_effects.bundle_save_candidates
    ] == ["root", "phase"]
    assert [item.artifacts_dir for item in plan.side_effects.artifact_delete_paths] == [
        "/tmp/plan",
        "/tmp/coder",
    ]
    assert [
        intent.new_name for intent in plan.side_effects.dismissal_rename_allocations
    ] == ["260430.a.plan", "260430.a.coder"]


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

    plan = plan_agent_cleanup_python(
        agents_to_cleanup_targets([running, done]), request
    )

    assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
    assert [item.cl_name for item in plan.side_effects.dismissed_index_additions] == [
        "done",
        "running",
    ]
    assert [
        item.workspace for item in plan.side_effects.workspace_release_requests
    ] == [9]
    assert [
        intent.new_name for intent in plan.side_effects.dismissal_rename_allocations
    ] == ["260430.done-name"]


def test_plan_agent_cleanup_uses_rust_binding_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents, request = _scenario_marked_set()
    targets = agents_to_cleanup_targets(agents)
    captured: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    def fake_plan(
        target_payload: list[dict[str, Any]], request_payload: dict[str, Any]
    ) -> dict[str, Any]:
        captured.append((target_payload, request_payload))
        plan = plan_agent_cleanup_python(target_payload, request_payload)
        payload = agent_cleanup_wire_to_json_dict(plan)
        payload["kill_items"][0]["kind"] = KILL_KIND_RUNNING
        return payload

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.plan_agent_cleanup = fake_plan  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    plan = plan_agent_cleanup(targets, request)

    assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
        ("running", KILL_KIND_RUNNING)
    ]
    assert captured == [
        (
            agent_cleanup_wire_to_json_dict(targets),
            agent_cleanup_wire_to_json_dict(request),
        )
    ]


def test_plan_agent_cleanup_falls_back_when_binding_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    agents, request = _scenario_marked_set()

    plan = plan_agent_cleanup(agents_to_cleanup_targets(agents), request)

    assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
    assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_rust_cleanup_planner_matches_python_reference(scenario: Any) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "plan_agent_cleanup"):
        pytest.skip("sase_core_rs is too old (no plan_agent_cleanup).")

    agents, request = scenario()
    targets = agents_to_cleanup_targets(agents)

    assert plan_agent_cleanup(targets, request) == plan_agent_cleanup_python(
        targets,
        request,
    )
