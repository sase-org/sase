"""Agents-tab agent-node ownership predicates and projections."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from .agent import Agent
from .agent_family_members import (
    concrete_family_member_rows,
    is_sequential_family_container,
)
from .agent_types import AgentType

AgentIdentity = tuple[AgentType, str, str | None]
AgentCompletionKey = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class _AgentNodeProjection:
    """One Agents-tab agent node and the concrete shells it owns."""

    node: Agent
    owned_rows: tuple[Agent, ...]
    completion_keys: tuple[AgentCompletionKey, ...]

    @property
    def identity(self) -> AgentIdentity:
        return self.node.identity


@dataclass(frozen=True, slots=True)
class _AgentNodeProjectionIndex:
    """Lookup tables for a complete loaded Agents-tab roster."""

    projections: tuple[_AgentNodeProjection, ...]
    by_node_identity: dict[AgentIdentity, _AgentNodeProjection]
    by_owned_identity: dict[AgentIdentity, _AgentNodeProjection]

    def owner_for_identity(
        self,
        identity: AgentIdentity,
    ) -> _AgentNodeProjection | None:
        """Return the owning agent-node projection for *identity*."""
        return self.by_node_identity.get(identity) or self.by_owned_identity.get(
            identity
        )


def is_agents_tab_agent_node(agent: Agent) -> bool:
    """Return whether *agent* is an Agents-tab agent node.

    Agent nodes are standalone root rows and sequential-family containers.
    Clan containers, family-member shells, workflow/step children, and durable
    shell rows are rendered nodes but not unread/countable agent nodes.
    The decision intentionally ignores visual tree depth: a standalone agent
    nested under a clan remains a direct agent node.
    """
    if getattr(agent, "is_clan_container", False):
        return False
    if getattr(agent, "is_monitor", False):
        return False
    if getattr(agent, "is_gate", False):
        return False
    if getattr(agent, "is_proc_shell", False):
        return False
    if getattr(agent, "is_workflow_step_child", False):
        return False
    if getattr(agent, "is_family_member_child", False):
        return False
    return True


def _agent_node_owned_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return concrete rows whose completion notifications project to *agent*."""
    if not is_agents_tab_agent_node(agent):
        return ()
    if is_sequential_family_container(agent):
        rows = concrete_family_member_rows(agent)
        return rows or (agent,)
    return (agent,)


def _agent_node_completion_rows(
    agent: Agent, owned_rows: Iterable[Agent] | None = None
) -> tuple[Agent, ...]:
    """Return rows whose completion notifications belong to *agent*.

    A node always owns the notification written under its own
    ``(cl_name, raw_suffix)``: the runner keys completions by the artifacts
    directory the node row was loaded from. Rows the node subsumes for status
    counting are additive, never a substitute -- ``concrete_family_member_rows``
    deliberately swaps a plan-family root for its concrete ``main`` workflow
    step, and step rows carry the step name as ``cl_name``.

    Workflow step children are excluded: they always share their node's
    ``raw_suffix`` and never own a distinct completion notification, so their
    step-name keys only widen the ``(cl_name, None)`` match surface.
    """
    if owned_rows is None:
        owned_rows = _agent_node_owned_rows(agent)
    owned = tuple(row for row in owned_rows if not row.is_workflow_step_child)
    return (agent, *owned)


def agent_node_completion_keys(agent: Agent) -> tuple[AgentCompletionKey, ...]:
    """Return notification completion keys owned by one agent node."""
    return _completion_keys_for_rows(_agent_node_completion_rows(agent))


def _completion_keys_for_rows(rows: Iterable[Agent]) -> tuple[AgentCompletionKey, ...]:
    keys: list[AgentCompletionKey] = []
    seen: set[AgentCompletionKey] = set()
    for row in rows:
        key = (row.cl_name, row.raw_suffix)
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return tuple(keys)


def agent_node_projection_index(
    agents: Iterable[Agent],
) -> _AgentNodeProjectionIndex:
    """Build an ownership index from a complete loaded roster."""
    roster = tuple(agents)
    node_agents: list[Agent] = []
    owned_by_node: dict[AgentIdentity, list[Agent]] = {}
    node_by_raw_suffix: dict[str, Agent] = {}
    seen_nodes: set[AgentIdentity] = set()
    for agent in roster:
        if not is_agents_tab_agent_node(agent):
            continue
        if agent.identity in seen_nodes:
            continue
        seen_nodes.add(agent.identity)
        node_agents.append(agent)
        owned_by_node[agent.identity] = list(_agent_node_owned_rows(agent))
        if agent.raw_suffix is not None:
            node_by_raw_suffix[agent.raw_suffix] = agent

    for agent in roster:
        if is_agents_tab_agent_node(agent):
            continue
        parent = node_by_raw_suffix.get(agent.parent_timestamp or "")
        if parent is None:
            continue
        owned_rows = owned_by_node[parent.identity]
        if all(row.identity != agent.identity for row in owned_rows):
            owned_rows.append(agent)

    projections: list[_AgentNodeProjection] = []
    by_node_identity: dict[AgentIdentity, _AgentNodeProjection] = {}
    by_owned_identity: dict[AgentIdentity, _AgentNodeProjection] = {}
    for agent in node_agents:
        owned_tuple = tuple(owned_by_node[agent.identity])
        projection = _AgentNodeProjection(
            node=agent,
            owned_rows=owned_tuple,
            completion_keys=_completion_keys_for_rows(
                _agent_node_completion_rows(agent, owned_tuple)
            ),
        )
        projections.append(projection)
        by_node_identity[projection.identity] = projection
        for row in owned_tuple:
            by_owned_identity.setdefault(row.identity, projection)
    return _AgentNodeProjectionIndex(
        projections=tuple(projections),
        by_node_identity=by_node_identity,
        by_owned_identity=by_owned_identity,
    )


def normalize_agent_node_identities(
    identities: Collection[AgentIdentity],
    index: _AgentNodeProjectionIndex,
) -> set[AgentIdentity]:
    """Project row identities onto owning agent-node identities."""
    normalized: set[AgentIdentity] = set()
    for identity in identities:
        projection = index.owner_for_identity(identity)
        if projection is not None:
            normalized.add(projection.identity)
    return normalized


def projection_has_active_completion(
    projection: _AgentNodeProjection,
    active_keys: Collection[AgentCompletionKey],
) -> bool:
    """Return whether *projection* is backed by any active completion key."""
    active = set(active_keys)
    return any(
        key in active or (key[0], None) in active for key in projection.completion_keys
    )


__all__ = [
    "AgentCompletionKey",
    "AgentIdentity",
    "agent_node_completion_keys",
    "agent_node_projection_index",
    "is_agents_tab_agent_node",
    "normalize_agent_node_identities",
    "projection_has_active_completion",
]
