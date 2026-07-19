"""Serialization helpers for Agents-tab repro rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .schema import ReproAgentRow

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sase.ace.tui.models.agent import Agent


def serialize_agent_row(agent: Agent) -> ReproAgentRow:
    """Return the commit-safe row fields needed by Phase 1 invariants."""

    metadata = {
        "llm_provider": agent.llm_provider,
        "vcs_provider": agent.vcs_provider,
        "role_suffix": agent.role_suffix,
        "retry_attempt": agent.retry_attempt,
        "appears_as_agent": agent.appears_as_agent,
    }
    return ReproAgentRow(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
        status=agent.status,
        parent_timestamp=agent.parent_timestamp,
        parent_workflow=agent.parent_workflow,
        workflow=agent.workflow,
        appears_as_agent=agent.appears_as_agent,
        step_type=agent.step_type,
        pid=agent.pid,
        workspace_num=agent.workspace_num,
        agent_name=agent.agent_name,
        tribe=agent.tribe,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def serialize_agent_rows(agents: Iterable[Agent]) -> list[ReproAgentRow]:
    return [serialize_agent_row(agent) for agent in agents]
