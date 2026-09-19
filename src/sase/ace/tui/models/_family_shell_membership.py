"""Attach unparented concrete family shells to their real family root.

Modern owner records often carry ``family_id`` / a plan-chain name suffix
without ``parent_timestamp``. A ``--plan`` gate with ``family_id`` is a
nested shell, never a second family container.
"""

from __future__ import annotations

from sase.plan_chain import (
    agent_family_role_for_suffix,
    is_agent_family_member,
)

from .agent import Agent

_SHELL_ROLES = frozenset({"plan", "code", "gate", "monitor", "proc", "member"})


def _is_concrete_family_shell(agent: Agent) -> bool:
    """Return whether *agent* is a nested family shell, not a root."""
    if agent.is_monitor or agent.is_gate or agent.is_proc_shell:
        return True
    role = agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    if role in _SHELL_ROLES:
        return True
    return is_agent_family_member(agent.agent_name) or is_agent_family_member(
        agent.role_suffix
    )


def attach_unparented_family_shells(agents: list[Agent]) -> None:
    """Fill missing ``parent_timestamp`` from the family's real root."""
    roots_by_family: dict[str, Agent] = {}
    for agent in agents:
        family = agent.agent_family
        if not family or agent.parent_timestamp:
            continue
        if _is_concrete_family_shell(agent):
            continue
        if agent.raw_suffix:
            roots_by_family.setdefault(family, agent)

    for agent in agents:
        if agent.parent_timestamp or not _is_concrete_family_shell(agent):
            continue
        family = agent.agent_family
        if not family:
            continue
        root = roots_by_family.get(family)
        if root is None or root is agent or not root.raw_suffix:
            continue
        agent.parent_timestamp = root.raw_suffix
