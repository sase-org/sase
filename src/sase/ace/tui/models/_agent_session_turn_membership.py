"""Attach unparented concrete session turns to their real session root.

Modern owner records carry an agent-session identity / a plan-chain name suffix
without ``parent_timestamp``. A ``--plan`` gate with an agent-session identity is a
nested turn, never a second session container.
"""

from __future__ import annotations

from sase.plan_chain import (
    agent_session_role_for_suffix,
    is_agent_session_member,
)

from .agent import Agent

_TURN_ROLES = frozenset({"plan", "code", "gate", "monitor", "proc", "member"})


def _is_concrete_agent_session_turn(agent: Agent) -> bool:
    """Return whether *agent* is a nested session turn, not a root."""
    if agent.is_monitor or agent.is_gate or agent.is_named_proc:
        return True
    role = agent_session_role_for_suffix(
        agent.role_suffix,
        agent_session_role=agent.agent_session_role,
    )
    if role in _TURN_ROLES:
        return True
    return is_agent_session_member(agent.agent_name) or is_agent_session_member(
        agent.role_suffix
    )


def attach_unparented_agent_session_turns(agents: list[Agent]) -> None:
    """Fill missing ``parent_timestamp`` from the agent session's real root."""
    roots_by_agent_session: dict[str, Agent] = {}
    for agent in agents:
        session_name = agent.agent_session
        if not session_name or agent.parent_timestamp:
            continue
        if _is_concrete_agent_session_turn(agent):
            continue
        if agent.raw_suffix:
            roots_by_agent_session.setdefault(session_name, agent)

    for agent in agents:
        if agent.parent_timestamp or not _is_concrete_agent_session_turn(agent):
            continue
        session_name = agent.agent_session
        if not session_name:
            continue
        root = roots_by_agent_session.get(session_name)
        if root is None or root is agent or not root.raw_suffix:
            continue
        agent.parent_timestamp = root.raw_suffix
