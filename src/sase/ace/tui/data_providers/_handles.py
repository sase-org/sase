"""Stable row-handle helpers for data-provider snapshots."""

from __future__ import annotations

from pathlib import Path

from ..models.agent import Agent
from ..provider_contract import AceRowHandle


def agent_row_handle(agent: Agent) -> AceRowHandle:
    """Return the stable ACE row handle for an agent row."""

    handle = daemon_handle_for_agent(agent)
    return AceRowHandle(
        surface="agents",
        stable_id=handle,
        daemon_handle=handle,
        local_identity="|".join(str(part) for part in agent.identity),
    )


def daemon_handle_for_agent(agent: Agent) -> str:
    project = Path(agent.project_file).parent.name if agent.project_file else "unknown"
    return f"agent:{project}:{agent.raw_suffix or ''}"
