"""Serialization helpers for Agents-tab repro rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .agent_factory import (
    agent_has_repro_identity,
    agent_to_repro_identity,
    agent_type_to_repro,
)
from .schema import AgentIdentity, ReproAgentRow

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sase.ace.tui.models.agent import Agent
    from sase.ace.tui.models.fold_state import FoldStateManager


def serialize_agent_row(agent: Agent) -> ReproAgentRow:
    """Return the commit-safe row fields needed by Phase 1 invariants."""

    agent_type = agent_type_to_repro(agent.agent_type)
    if agent_type is None:
        raise ValueError(
            f"agent type {agent.agent_type.value!r} is not repro-serializable"
        )
    metadata = {
        "llm_provider": agent.llm_provider,
        "vcs_provider": agent.vcs_provider,
        "role_suffix": agent.role_suffix,
        "retry_attempt": agent.retry_attempt,
        "appears_as_agent": agent.appears_as_agent,
    }
    return ReproAgentRow(
        agent_type=agent_type,
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
    return [
        serialize_agent_row(agent)
        for agent in agents
        if agent_has_repro_identity(agent)
    ]


def serialize_unfiltered_roster(
    agents: Iterable[Agent],
    fold_manager: FoldStateManager | None,
) -> tuple[list[AgentIdentity], list[AgentIdentity]]:
    """Return the unfiltered roster's identities and the fold-explained subset.

    The second list holds the rows a fold level legitimately keeps out of the
    published roster: the rows the fold filter hides. A clan container is not
    among them (the fold keeps it and hides only its members), so a published
    roster missing the container of a collapsed clan is a defect the
    roster-coverage invariant must see. Returns two empty lists when the fold
    cannot be evaluated, which disables the invariant instead of letting it
    guess.
    """
    from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state

    rows = list(agents)
    if fold_manager is None:
        return [], []
    try:
        fold_visible, _ = filter_agents_by_fold_state(rows, fold_manager)
    except Exception:
        return [], []
    fold_visible_ids = {id(agent) for agent in fold_visible}
    repro_rows = [agent for agent in rows if agent_has_repro_identity(agent)]
    return (
        [agent_to_repro_identity(agent) for agent in repro_rows],
        [
            agent_to_repro_identity(agent)
            for agent in repro_rows
            if id(agent) not in fold_visible_ids
        ],
    )
