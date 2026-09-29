"""Scope and workflow scenarios for agent cleanup facade tests."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_cleanup_wire import (
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_GROUP,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TRIBE,
    AgentCleanupRequestWire,
)
from tests.test_core_facade._agent_cleanup_builders import (
    STOP_TIME,
    make_agent,
    make_identity,
    make_request,
)


def scenario_focused_panel_dismiss() -> tuple[list[Agent], AgentCleanupRequestWire]:
    done = make_agent(cl_name="done", status="DONE", pid=None, tribe="focus")
    running = make_agent(cl_name="running", status="RUNNING", pid=101, tribe="focus")
    other = make_agent(cl_name="other", status="DONE", pid=None, tribe="other")
    return [
        done,
        running,
        other,
    ], make_request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        focused_panel_tribe="focus",
    )


def scenario_focused_panel_kill_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    running = make_agent(cl_name="running", status="RUNNING", pid=101, tribe=None)
    done = make_agent(
        cl_name="done", status="FAILED", pid=None, tribe=None, stop_time=STOP_TIME
    )
    other = make_agent(cl_name="other", status="DONE", pid=None, tribe="other")
    return [
        running,
        done,
        other,
    ], make_request(
        scope=CLEANUP_SCOPE_FOCUSED_PANEL,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        focused_panel_tribe=None,
    )


def scenario_marked_set() -> tuple[list[Agent], AgentCleanupRequestWire]:
    running = make_agent(cl_name="running", status="RUNNING", pid=101)
    done = make_agent(cl_name="done", status="DONE", pid=None)
    unmarked = make_agent(cl_name="unmarked", status="RUNNING", pid=202)
    return [
        running,
        done,
        unmarked,
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(running), make_identity(done)),
    )


def scenario_collapsed_group() -> tuple[list[Agent], AgentCleanupRequestWire]:
    running = make_agent(cl_name="group-running", status="RUNNING", pid=101)
    done = make_agent(cl_name="group-done", status="DONE", pid=None)
    outside = make_agent(cl_name="outside", status="RUNNING", pid=202)
    return [
        running,
        done,
        outside,
    ], make_request(
        scope=CLEANUP_SCOPE_FOCUSED_GROUP,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(running), make_identity(done)),
    )


def scenario_tribe_scope() -> tuple[list[Agent], AgentCleanupRequestWire]:
    alpha = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="alpha",
        status="RUNNING",
        pid=101,
        raw_suffix="alpha-ts",
        workflow="deploy",
        tribe="alpha",
    )
    child = make_agent(
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
    beta = make_agent(
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
    ], make_request(
        scope=CLEANUP_SCOPE_TRIBE,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        tribe="alpha",
    )


def scenario_clan_scope() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="release",
        status="RUNNING",
        pid=101,
        raw_suffix="parent-ts",
        workflow="release",
        agent_clan="shipping",
        agent_clan_generation="current-gen",
    )
    child = make_agent(
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
    done = make_agent(
        cl_name="verified",
        status="DONE",
        pid=None,
        raw_suffix="done-ts",
        stop_time=STOP_TIME,
        agent_clan="shipping",
        agent_clan_generation="current-gen",
    )
    stale = make_agent(
        cl_name="stale",
        pid=201,
        raw_suffix="stale-ts",
        agent_clan="shipping",
        agent_clan_generation="stale-gen",
    )
    other = make_agent(
        cl_name="other",
        pid=202,
        raw_suffix="other-ts",
        agent_clan="research",
        agent_clan_generation="current-gen",
    )
    return [parent, child, done, stale, other], make_request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        clan_name="shipping",
        clan_generation="current-gen",
    )


def scenario_clan_scope_active_parallel_agent_session() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    root = make_agent(
        cl_name="agent_session",
        raw_suffix="root-ts",
        status="DONE",
        pid=None,
        stop_time=STOP_TIME,
        agent_session_parallel=True,
        agent_clan="research",
        agent_clan_generation="generation",
    )
    member = make_agent(
        cl_name="agent_session.1",
        raw_suffix="member-ts",
        pid=101,
        parent_timestamp="root-ts",
        agent_session_parallel=True,
        agent_clan="research",
        agent_clan_generation="generation",
    )
    return [root, member], make_request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        clan_name="research",
        clan_generation="generation",
    )


def scenario_workflow_parent_with_children() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="RUNNING",
        pid=1001,
        raw_suffix="parent-ts",
        workflow="release",
    )
    child = make_agent(
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
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(parent),),
    )


def scenario_pidless_dismiss_fallback() -> tuple[list[Agent], AgentCleanupRequestWire]:
    pidless = make_agent(cl_name="pidless", status="RUNNING", pid=None)
    return [
        pidless,
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(pidless),),
        include_pidless_as_dismissable=True,
    )


def scenario_duplicate_child_inputs() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="RUNNING",
        pid=1001,
        raw_suffix="parent-ts",
        workflow="release",
    )
    child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="child",
        status="RUNNING",
        pid=1002,
        raw_suffix="child-ts",
        workflow="release",
        parent_workflow="release",
        parent_timestamp="parent-ts",
    )
    duplicate_child = make_agent(
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
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(parent), make_identity(child)),
    )


__all__ = [
    "scenario_clan_scope",
    "scenario_clan_scope_active_parallel_agent_session",
    "scenario_collapsed_group",
    "scenario_duplicate_child_inputs",
    "scenario_focused_panel_dismiss",
    "scenario_focused_panel_kill_dismiss",
    "scenario_marked_set",
    "scenario_pidless_dismiss_fallback",
    "scenario_tribe_scope",
    "scenario_workflow_parent_with_children",
]
