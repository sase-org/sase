"""Agent-name matching for commit-finalizer provenance."""

from __future__ import annotations


def agent_provenance_matches(recorded_agent: str | None, agent_name: str) -> bool:
    """Return whether a commit trailer name identifies *agent_name*."""
    if not recorded_agent:
        return False
    if _names_match(recorded_agent, agent_name):
        return True
    return _names_match(_sase_agent_of(recorded_agent), _sase_agent_of(agent_name))


def _names_match(recorded_agent: str, agent_name: str) -> bool:
    return recorded_agent == agent_name or recorded_agent.startswith(
        (f"{agent_name}.", f"{agent_name}--")
    )


def _sase_agent_of(name: str) -> str:
    try:
        from sase.core.agent_identity_facade import AgentIdentitySnapshot
        from sase.sase_agent import sase_agent_ref_for_turn

        return sase_agent_ref_for_turn(name, AgentIdentitySnapshot.current()).local_name
    except Exception:
        return name


__all__ = ["agent_provenance_matches"]
