"""Shared helpers for agent cleanup facade tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_GROUP,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TRIBE,
    AgentCleanupIdentityWire,
    AgentCleanupRequestWire,
)


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
    agent_family_parallel: bool = False,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    tribe: str | None = None,
    agent_name: str | None = None,
    agent_family_role: str | None = None,
    role_suffix: str | None = None,
    monitor_id: str | None = None,
    monitor_state: str | None = None,
    workspace_num: int | None = 7,
    artifacts_dir: str | None = "/tmp/artifacts",
    start_time: datetime | None = _START,
    stop_time: datetime | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/project.sase",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        workspace_num=workspace_num,
        workflow=workflow,
        pid=pid,
        raw_suffix=raw_suffix,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        agent_family_parallel=agent_family_parallel,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
        tribe=tribe,
        agent_name=agent_name,
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
        monitor_id=monitor_id,
        monitor_state=monitor_state,
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
    focused_panel_tribe: str | None = None,
    tribe: str | None = None,
    clan_name: str | None = None,
    clan_generation: str | None = None,
    identities: tuple[AgentCleanupIdentityWire, ...] = (),
    include_pidless_as_dismissable: bool = False,
) -> AgentCleanupRequestWire:
    return AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=scope,
        mode=mode,
        focused_panel_tribe=focused_panel_tribe,
        tribe=tribe,
        clan_name=clan_name,
        clan_generation=clan_generation,
        identities=identities,
        include_pidless_as_dismissable=include_pidless_as_dismissable,
    )


def _scenario_focused_panel_dismiss() -> tuple[list[Agent], AgentCleanupRequestWire]:
    done = _agent(cl_name="done", status="DONE", pid=None, tribe="focus")
    running = _agent(cl_name="running", status="RUNNING", pid=101, tribe="focus")
    other = _agent(cl_name="other", status="DONE", pid=None, tribe="other")
    return [
        done,
        running,
        other,
    ], _request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        focused_panel_tribe="focus",
    )


def _scenario_focused_panel_kill_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    running = _agent(cl_name="running", status="RUNNING", pid=101, tribe=None)
    done = _agent(
        cl_name="done", status="FAILED", pid=None, tribe=None, stop_time=_STOP
    )
    other = _agent(cl_name="other", status="DONE", pid=None, tribe="other")
    return [
        running,
        done,
        other,
    ], _request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        focused_panel_tribe=None,
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


def _scenario_tribe_scope() -> tuple[list[Agent], AgentCleanupRequestWire]:
    alpha = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="alpha",
        status="RUNNING",
        pid=101,
        raw_suffix="alpha-ts",
        workflow="deploy",
        tribe="alpha",
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="alpha-child",
        status="RUNNING",
        pid=102,
        raw_suffix="child",
        workflow="deploy",
        parent_workflow="deploy",
        parent_timestamp=alpha.raw_suffix,
        tribe=None,
    )
    beta = _agent(
        cl_name="beta",
        status="RUNNING",
        pid=201,
        raw_suffix="beta-ts",
        tribe="beta",
    )
    return [
        alpha,
        child,
        beta,
    ], _request(
        scope=CLEANUP_SCOPE_TRIBE,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        tribe="alpha",
    )


def _scenario_clan_scope() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="release",
        status="RUNNING",
        pid=101,
        raw_suffix="parent-ts",
        workflow="release",
        agent_clan="shipping",
        agent_clan_generation="current-gen",
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="release-step",
        status="RUNNING",
        pid=102,
        raw_suffix="child-ts",
        workflow="release",
        parent_workflow="release",
        parent_timestamp="parent-ts",
        agent_clan="shipping",
        agent_clan_generation="current-gen",
    )
    done = _agent(
        cl_name="verified",
        status="DONE",
        pid=None,
        raw_suffix="done-ts",
        stop_time=_STOP,
        agent_clan="shipping",
        agent_clan_generation="current-gen",
    )
    stale = _agent(
        cl_name="stale",
        pid=201,
        raw_suffix="stale-ts",
        agent_clan="shipping",
        agent_clan_generation="stale-gen",
    )
    other = _agent(
        cl_name="other",
        pid=202,
        raw_suffix="other-ts",
        agent_clan="research",
        agent_clan_generation="current-gen",
    )
    return [parent, child, done, stale, other], _request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        clan_name="shipping",
        clan_generation="current-gen",
    )


def _scenario_clan_scope_active_parallel_family() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    root = _agent(
        cl_name="family",
        raw_suffix="root-ts",
        status="DONE",
        pid=None,
        stop_time=_STOP,
        agent_family_parallel=True,
        agent_clan="research",
        agent_clan_generation="generation",
    )
    member = _agent(
        cl_name="family.1",
        raw_suffix="member-ts",
        pid=101,
        parent_timestamp="root-ts",
        agent_family_parallel=True,
        agent_clan="research",
        agent_clan_generation="generation",
    )
    return [root, member], _request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        clan_name="research",
        clan_generation="generation",
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


def _scenario_explicit_child_running() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = _agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = _agent(
        cl_name="child",
        raw_suffix="child-ts",
        pid=1002,
        parent_timestamp="parent-ts",
        workspace_num=8,
    )
    sibling = _agent(
        cl_name="sibling",
        raw_suffix="sibling-ts",
        pid=1003,
        parent_timestamp="parent-ts",
        workspace_num=9,
    )
    return [
        parent,
        child,
        sibling,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(child),),
    )


def _scenario_explicit_child_done() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = _agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = _agent(
        cl_name="child",
        raw_suffix="child-ts",
        status="DONE",
        pid=None,
        parent_timestamp="parent-ts",
        stop_time=_STOP,
    )
    return [
        parent,
        child,
    ], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(child),),
    )


def _scenario_custom_child_running() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = _agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = _agent(
        cl_name="child",
        raw_suffix="child-ts",
        pid=1002,
        parent_timestamp="parent-ts",
    )
    return [
        parent,
        child,
    ], _request(
        scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(child),),
    )


def _scenario_parallel_family_root() -> tuple[list[Agent], AgentCleanupRequestWire]:
    root = _agent(
        cl_name="sase-6g",
        raw_suffix="root-ts",
        pid=1001,
        agent_family_parallel=True,
    )
    member = _agent(
        cl_name="sase-6g.1",
        raw_suffix="member-ts",
        pid=1002,
        parent_timestamp="root-ts",
        agent_family_parallel=True,
    )
    serial_child = _agent(
        cl_name="sase-6g--code",
        raw_suffix="serial-ts",
        pid=1003,
        parent_timestamp="root-ts",
    )
    return [root, member, serial_child], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(root),),
    )


def _clan_sequential_family_agents() -> list[Agent]:
    plan_root = _agent(
        cl_name="sase-ps.plan",
        raw_suffix="20260818102050",
        status="DONE",
        pid=None,
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_family_parallel=False,
        stop_time=_STOP,
    )
    family_root = _agent(
        cl_name="sase-ps.plan--1",
        raw_suffix="20260818114621",
        status="DONE",
        pid=None,
        parent_timestamp="20260818102050",
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_family_parallel=False,
        stop_time=_STOP,
    )
    monitor = _agent(
        cl_name="sase-ps.plan--mon",
        raw_suffix="20260818114457",
        status="DONE",
        pid=None,
        parent_timestamp="20260818114621",
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_family_parallel=False,
        stop_time=_STOP,
    )
    return [plan_root, family_root, monitor]


def _scenario_clan_sequential_family_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    agents = _clan_sequential_family_agents()
    return agents, _request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        clan_name="sase-ps",
        clan_generation="20260818102050",
        include_pidless_as_dismissable=True,
    )


def _scenario_explicit_clan_sequential_family_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    agents = _clan_sequential_family_agents()
    return agents, _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=tuple(_id(agent) for agent in agents),
        include_pidless_as_dismissable=True,
    )


def _live_monitor(
    *,
    cl_name: str,
    raw_suffix: str,
    parent_timestamp: str,
    monitor_id: str,
    pid: int | None = 1665545,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
) -> Agent:
    return _agent(
        cl_name=cl_name,
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        status="MONITORING",
        pid=pid,
        workspace_num=15,
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id=monitor_id,
        monitor_state="running",
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
    )


def _scenario_direct_live_monitor() -> tuple[list[Agent], AgentCleanupRequestWire]:
    owner = _agent(
        cl_name="owner",
        raw_suffix="owner-ts",
        status="DONE",
        pid=None,
        stop_time=_STOP,
    )
    monitor = _live_monitor(
        cl_name="owner--mon",
        raw_suffix="mon-ts",
        parent_timestamp="owner-ts",
        monitor_id="monid123456",
    )
    return [owner, monitor], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(monitor),),
    )


def _scenario_owner_cascades_live_monitor() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    owner = _agent(
        cl_name="sase-ru.6",
        raw_suffix="owner-ts",
        status="DONE",
        pid=None,
        stop_time=_STOP,
    )
    family = _agent(
        cl_name="sase-ru.6--1",
        raw_suffix="family-ts",
        parent_timestamp="owner-ts",
        status="DONE",
        pid=None,
        stop_time=_STOP,
    )
    monitor = _live_monitor(
        cl_name="sase-ru.6--mon-1",
        raw_suffix="mon-ts",
        parent_timestamp="family-ts",
        monitor_id="0fmbm91hgytw",
    )
    sibling = _live_monitor(
        cl_name="sase-ru.7--mon",
        raw_suffix="sib-mon-ts",
        parent_timestamp="sib-ts",
        monitor_id="unrelatedmon1",
    )
    return [owner, family, monitor, sibling], _request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(_id(owner),),
    )


_SCENARIOS = [
    pytest.param(_scenario_focused_panel_dismiss, id="focused-panel-dismiss-done"),
    pytest.param(
        _scenario_focused_panel_kill_dismiss,
        id="focused-panel-kill-dismiss",
    ),
    pytest.param(_scenario_marked_set, id="marked-set"),
    pytest.param(_scenario_collapsed_group, id="collapsed-group"),
    pytest.param(_scenario_tribe_scope, id="tribe-scope"),
    pytest.param(_scenario_clan_scope, id="clan-scope"),
    pytest.param(
        _scenario_clan_scope_active_parallel_family,
        id="clan-scope-active-parallel-family",
    ),
    pytest.param(
        _scenario_workflow_parent_with_children,
        id="workflow-parent-cascade",
    ),
    pytest.param(_scenario_pidless_dismiss_fallback, id="pidless-dismiss-fallback"),
    pytest.param(_scenario_duplicate_child_inputs, id="duplicate-child-inputs"),
    pytest.param(_scenario_explicit_child_running, id="explicit-child-running"),
    pytest.param(_scenario_explicit_child_done, id="explicit-child-done"),
    pytest.param(_scenario_custom_child_running, id="custom-child-running"),
    pytest.param(_scenario_parallel_family_root, id="parallel-family-root"),
    pytest.param(
        _scenario_clan_sequential_family_dismiss,
        id="clan-sequential-family-dismiss",
    ),
    pytest.param(
        _scenario_explicit_clan_sequential_family_dismiss,
        id="explicit-clan-sequential-family-dismiss",
    ),
    pytest.param(_scenario_direct_live_monitor, id="direct-live-monitor"),
    pytest.param(_scenario_owner_cascades_live_monitor, id="owner-cascade-monitor"),
]
