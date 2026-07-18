"""Shared helpers for the ``test_agent_groups_*`` test modules."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import TreeEntry

_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.sase",
    tag: str | None = None,
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    status: str = "RUNNING",
    start_time: datetime | None = datetime(2026, 4, 25, 12, 0, 0),
    stop_time: datetime | None = None,
    wait_until: str | None = None,
    waiting_for: list[str] | None = None,
    retried_as_timestamp: str | None = None,
    role_suffix: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tag=tag,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        wait_until=wait_until,
        waiting_for=list(waiting_for) if waiting_for is not None else [],
        retried_as_timestamp=retried_as_timestamp,
    )
    agent.role_suffix = role_suffix
    agent.agent_family = agent_family
    agent.agent_family_role = agent_family_role
    return agent


def _kinds(entries: list[TreeEntry]) -> list[tuple[str, int | None]]:
    """Reduce entries to (kind, level/agent_idx) pairs for readable assertions."""
    out: list[tuple[str, int | None]] = []
    for e in entries:
        if e.kind == "group":
            assert e.group is not None
            out.append(("group", e.group.level))
        else:
            out.append(("agent", e.agent_idx))
    return out


def _group_keys(entries: list[TreeEntry], level: int) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == level
    ]


def _anchored_clan_agents() -> list[Agent]:
    """Return a clan whose grandchildren carry conflicting presentation data."""
    generation = "20260718080000"
    phase = _agent(
        cl_name="phase-changespec",
        project_file="/r/root/root.sase",
        tag="epic",
        agent_name="sase-6r.phase-plan",
        raw_suffix="phase",
        status="DONE",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    phase.agent_clan = "sase-6r"
    phase.agent_clan_generation = generation
    ordinary = _agent(
        cl_name="descendant-changespec",
        project_file="/r/other/other.sase",
        tag="review",
        agent_name="detached.family.step",
        raw_suffix="ordinary",
        parent_workflow="phase",
        parent_timestamp="phase",
        status="QUESTION",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    hidden = _agent(
        cl_name="hidden-changespec",
        project_file="/r/hidden/hidden.sase",
        tag="hidden",
        agent_name="hidden.family.step",
        raw_suffix="hidden",
        parent_workflow="phase",
        parent_timestamp="phase",
        status="FAILED",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    hidden.is_hidden_step = True
    peer = _agent(
        cl_name="peer-changespec",
        project_file="/r/root/root.sase",
        tag="review",
        agent_name="sase-6r.phase-review",
        raw_suffix="peer",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    peer.agent_clan = "sase-6r"
    peer.agent_clan_generation = generation
    return project_clan_tree([phase, ordinary, hidden, peer])
