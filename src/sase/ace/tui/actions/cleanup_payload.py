"""JSON-safe cleanup persistence payloads for durable agent operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType


def _json_identity(identity: tuple[Any, ...]) -> list[Any]:
    """Serialize one dismissed/kill identity without enum objects."""
    agent_type, cl_name, suffix = identity[0], identity[1], identity[2]
    return [getattr(agent_type, "value", str(agent_type)), str(cl_name), suffix]


def json_identities(identities: Iterable[tuple[Any, ...]]) -> list[list[Any]]:
    """Serialize a set or sequence of agent identities."""
    return [_json_identity(item) for item in identities]


def _identity_from_json(item: object) -> tuple[AgentType, str, str | None]:
    """Rehydrate one identity from a JSON list."""
    if not isinstance(item, list) or len(item) < 2:
        raise ValueError(f"invalid cleanup identity: {item!r}")
    suffix = item[2] if len(item) > 2 else None
    return (
        AgentType(str(item[0])),
        str(item[1]),
        None if suffix is None else str(suffix),
    )


def identities_from_json(raw: object) -> set[tuple[AgentType, str, str | None]]:
    """Rehydrate a dismissed-identity snapshot from JSON."""
    if not isinstance(raw, list):
        return set()
    return {_identity_from_json(item) for item in raw if isinstance(item, list)}


def serialize_agent(agent: Agent) -> dict[str, Any]:
    """Project persist-relevant Agent fields into a JSON object."""
    start = agent.start_time
    return {
        "agent_clan": agent.agent_clan,
        "agent_family_role": agent.agent_family_role,
        "agent_name": agent.agent_name,
        "agent_type": agent.agent_type.value,
        "artifacts_dir": agent.artifacts_dir,
        "cl_name": agent.cl_name,
        "clan_tribe": agent.clan_tribe,
        "from_patch": bool(agent._from_patch),
        "gate_accent": agent.gate_accent,
        "gate_id": agent.gate_id,
        "gate_kind": agent.gate_kind,
        "gate_label": agent.gate_label,
        "gate_start_status": agent.gate_start_status,
        "gate_state": agent.gate_state,
        "gate_stop_status": agent.gate_stop_status,
        "hook_command": agent.hook_command,
        "mentor_name": agent.mentor_name,
        "mentor_profile": agent.mentor_profile,
        "monitor_id": agent.monitor_id,
        "monitor_state": agent.monitor_state,
        "parent_timestamp": agent.parent_timestamp,
        "parent_workflow": agent.parent_workflow,
        "pid": agent.pid,
        "project_file": agent.project_file,
        "raw_suffix": agent.raw_suffix,
        "reviewer": agent.reviewer,
        "role_suffix": agent.role_suffix,
        "start_time": start.isoformat() if isinstance(start, datetime) else None,
        "status": agent.status,
        "tribe": agent.tribe,
        "workflow": agent.workflow,
        "workspace_num": agent.workspace_num,
    }


def serialize_agents(agents: Iterable[Agent] | None) -> list[dict[str, Any]]:
    """Serialize a sequence of agents for a cleanup request."""
    if not agents:
        return []
    return [serialize_agent(agent) for agent in agents]


def agent_from_json(data: Mapping[str, Any]) -> Agent:
    """Rehydrate a persist-capable Agent from a cleanup payload."""
    start_raw = data.get("start_time")
    start = datetime.fromisoformat(start_raw) if isinstance(start_raw, str) else None
    agent = Agent(
        agent_type=AgentType(str(data.get("agent_type") or "running")),
        cl_name=str(data.get("cl_name") or ""),
        project_file=str(data.get("project_file") or ""),
        status=str(data.get("status") or "DONE"),
        start_time=start,
        workflow=data.get("workflow")
        if isinstance(data.get("workflow"), str)
        else None,
        pid=data.get("pid") if isinstance(data.get("pid"), int) else None,
        raw_suffix=(
            data.get("raw_suffix") if isinstance(data.get("raw_suffix"), str) else None
        ),
        workspace_num=(
            data.get("workspace_num")
            if isinstance(data.get("workspace_num"), int)
            else None
        ),
        artifacts_dir=(
            data.get("artifacts_dir")
            if isinstance(data.get("artifacts_dir"), str)
            else None
        ),
        parent_workflow=(
            data.get("parent_workflow")
            if isinstance(data.get("parent_workflow"), str)
            else None
        ),
        parent_timestamp=(
            data.get("parent_timestamp")
            if isinstance(data.get("parent_timestamp"), str)
            else None
        ),
        hook_command=(
            data.get("hook_command")
            if isinstance(data.get("hook_command"), str)
            else None
        ),
        mentor_profile=(
            data.get("mentor_profile")
            if isinstance(data.get("mentor_profile"), str)
            else None
        ),
        mentor_name=(
            data.get("mentor_name")
            if isinstance(data.get("mentor_name"), str)
            else None
        ),
        reviewer=data.get("reviewer")
        if isinstance(data.get("reviewer"), str)
        else None,
        tribe=data.get("tribe") if isinstance(data.get("tribe"), str) else None,
        agent_name=(
            data.get("agent_name") if isinstance(data.get("agent_name"), str) else None
        ),
        agent_clan=(
            data.get("agent_clan") if isinstance(data.get("agent_clan"), str) else None
        ),
        agent_family_role=(
            data.get("agent_family_role")
            if isinstance(data.get("agent_family_role"), str)
            else None
        ),
        role_suffix=(
            data.get("role_suffix")
            if isinstance(data.get("role_suffix"), str)
            else None
        ),
        gate_id=data.get("gate_id") if isinstance(data.get("gate_id"), str) else None,
        gate_kind=(
            data.get("gate_kind") if isinstance(data.get("gate_kind"), str) else None
        ),
        gate_state=(
            data.get("gate_state") if isinstance(data.get("gate_state"), str) else None
        ),
        gate_start_status=(
            data.get("gate_start_status")
            if isinstance(data.get("gate_start_status"), str)
            else None
        ),
        gate_stop_status=(
            data.get("gate_stop_status")
            if isinstance(data.get("gate_stop_status"), str)
            else None
        ),
        gate_accent=(
            data.get("gate_accent")
            if isinstance(data.get("gate_accent"), str)
            else None
        ),
        gate_label=(
            data.get("gate_label") if isinstance(data.get("gate_label"), str) else None
        ),
        monitor_id=(
            data.get("monitor_id") if isinstance(data.get("monitor_id"), str) else None
        ),
        monitor_state=(
            data.get("monitor_state")
            if isinstance(data.get("monitor_state"), str)
            else None
        ),
        clan_tribe=(
            data.get("clan_tribe") if isinstance(data.get("clan_tribe"), str) else None
        ),
    )
    if data.get("from_patch"):
        agent._from_patch = True
    return agent


def agents_from_json(raw: object) -> list[Agent]:
    """Rehydrate a list of agents from JSON."""
    if not isinstance(raw, list):
        return []
    return [agent_from_json(item) for item in raw if isinstance(item, dict)]


__all__ = [
    "agent_from_json",
    "agents_from_json",
    "identities_from_json",
    "json_identities",
    "serialize_agent",
    "serialize_agents",
]
