"""State bucketing and role predicates for agent-session shell kinds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.plan_chain import agent_session_role_for_suffix


@dataclass(frozen=True, slots=True)
class TurnStateConfig:
    """State bucket map and agent-session role for one shell kind."""

    agent_session_role: str
    buckets: Mapping[str, str]
    running_bucket: str = "Running"


def turn_state_bucket(shell_state: str | None, config: TurnStateConfig) -> str:
    """Return the status bucket for *shell_state*."""
    return config.buckets.get(shell_state or "", config.running_bucket)


def turn_state_is_terminal(
    shell_state: str | None,
    config: TurnStateConfig,
) -> bool:
    """Return whether *shell_state* has reached a terminal bucket."""
    return turn_state_bucket(shell_state, config) != config.running_bucket


def is_turn_member_role(
    agent_session_role: str | None,
    role_suffix: str | None = None,
    *,
    config: TurnStateConfig,
) -> bool:
    """Return whether a row is a member for *config*'s shell role."""
    if isinstance(agent_session_role, str) and agent_session_role.strip():
        return agent_session_role.strip() == config.agent_session_role
    return agent_session_role_for_suffix(role_suffix) == config.agent_session_role


def is_real_turn_member(
    agent_session_role: str | None,
    shell_id: str | None,
    *,
    config: TurnStateConfig,
) -> bool:
    """Return whether a row is the durable member for this shell kind."""
    return (
        isinstance(agent_session_role, str)
        and agent_session_role.strip() == config.agent_session_role
        and isinstance(shell_id, str)
        and bool(shell_id.strip())
    )


__all__ = [
    "TurnStateConfig",
    "is_real_turn_member",
    "is_turn_member_role",
    "turn_state_bucket",
    "turn_state_is_terminal",
]
