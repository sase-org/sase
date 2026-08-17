"""Shared helpers for the ``test_agent_tree*`` test modules."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType

_GENERATION = "20260717100000"


def _agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    step_type: str | None = None,
    hidden: bool = False,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
    tribe: str | None = None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/sase.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        run_start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type=step_type,
        is_hidden_step=hidden,
        agent_clan=clan,
        agent_clan_generation=generation,
        tribe=tribe,
        clan_tribe=clan_tribe,
        clan_summary=clan_summary,
    )
