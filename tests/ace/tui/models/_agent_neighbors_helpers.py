"""Shared helpers for the ``test_agent_neighbor*`` test modules."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.agent_hoods import AgentNeighborRow
from sase.core.time import local_now


def _agent(
    name: str | None,
    *,
    status: str = "RUNNING",
    tribe: str | None = None,
    suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/r/proj/proj.sase",
        status=status,
        start_time=local_now(),
        raw_suffix=suffix or name,
        agent_name=name,
        tribe=tribe,
    )


def _agent_session_root(session_name: str, *, role: str = "plan") -> Agent:
    """Return a session root entry that renders under its bare session base."""
    root = _agent(f"{session_name}--{role}")
    root.agent_session = session_name
    root.agent_session_role = "root"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    return root


def _agent_session_member(session_name: str, *, role: str, parent: Agent) -> Agent:
    """Return a concrete session-member child row of ``parent``."""
    member = _agent(f"{session_name}--{role}")
    member.agent_session = session_name
    member.agent_session_role = role
    member.parent_timestamp = parent.raw_suffix
    parent.followup_agents = [*parent.followup_agents, member]
    return member


def _rows_from_tree(
    agents: list[Agent], registry: AgentGroupFoldRegistry
) -> list[AgentNeighborRow]:
    tree = build_agent_tree(agents, fold_registry=registry)
    return [
        AgentNeighborRow(entry.agent_idx, 0, agents[entry.agent_idx])
        for entry in tree
        if entry.kind == "agent" and entry.agent_idx is not None
    ]
