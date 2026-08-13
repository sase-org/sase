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


def _family_root(family: str, *, role: str = "plan") -> Agent:
    """Return a family root entry that renders under its bare family base."""
    root = _agent(f"{family}--{role}")
    root.agent_family = family
    root.agent_family_role = "root"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    return root


def _family_member(family: str, *, role: str, parent: Agent) -> Agent:
    """Return a concrete family-member child row of ``parent``."""
    member = _agent(f"{family}--{role}")
    member.agent_family = family
    member.agent_family_role = role
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
