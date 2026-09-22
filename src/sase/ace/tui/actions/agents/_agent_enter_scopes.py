"""Scope classification for Enter-target resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.gate_shell.state import gate_state_is_terminal
from sase.project_display_names import humanize_cl_name

from ...models.agent_family_members import family_roster_container

if TYPE_CHECKING:
    from ...models import Agent


def is_pending_gate_row(row: Agent) -> bool:
    return (
        bool(getattr(row, "is_gate", False))
        and getattr(row, "gate_state", None) == "pending"
        and getattr(row, "stop_time", None) is None
        and not bool(getattr(row, "gate_execution_active", False))
    )


def is_settled_gate_row(row: Agent) -> bool:
    if not bool(getattr(row, "is_gate", False)):
        return False
    if getattr(row, "stop_time", None) is not None:
        return True
    return bool(gate_state_is_terminal(getattr(row, "gate_state", None)))


def classify_scope(agent: Agent) -> str:
    if bool(getattr(agent, "is_clan_container", False)):
        return "clan"
    if bool(getattr(agent, "is_monitor", False)) or bool(
        getattr(agent, "is_proc_shell", False)
    ):
        return "monitor_proc"
    if bool(getattr(agent, "is_gate", False)):
        return "gate"
    if getattr(agent, "fleet_origin_alias", None):
        return "remote"
    if getattr(agent, "parent_workflow", None) is not None or bool(
        getattr(agent, "is_workflow_step_child", False)
    ):
        return "workflow_step"
    if bool(getattr(agent, "is_family_container_row", False)):
        return "container"
    if family_roster_container(agent) is not None:
        return "member"
    return "standalone"


def scope_title(agent: Agent) -> str:
    presented = getattr(agent, "presented_agent_name", None)
    if isinstance(presented, str) and presented.strip():
        return presented.strip()
    name = getattr(agent, "agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    cl_name = getattr(agent, "cl_name", None) or ""
    return humanize_cl_name(str(cl_name)) if cl_name else ""


__all__ = [
    "classify_scope",
    "is_pending_gate_row",
    "is_settled_gate_row",
    "scope_title",
]
