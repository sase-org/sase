"""State bucketing and role predicates for family shell kinds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.plan_chain import agent_family_role_for_suffix


@dataclass(frozen=True, slots=True)
class ShellStateConfig:
    """State bucket map and family role for one shell kind."""

    family_role: str
    buckets: Mapping[str, str]
    running_bucket: str = "Running"


def shell_state_bucket(shell_state: str | None, config: ShellStateConfig) -> str:
    """Return the status bucket for *shell_state*."""
    return config.buckets.get(shell_state or "", config.running_bucket)


def shell_state_is_terminal(
    shell_state: str | None,
    config: ShellStateConfig,
) -> bool:
    """Return whether *shell_state* has reached a terminal bucket."""
    return shell_state_bucket(shell_state, config) != config.running_bucket


def is_shell_member_role(
    agent_family_role: str | None,
    role_suffix: str | None = None,
    *,
    config: ShellStateConfig,
) -> bool:
    """Return whether a row is a member for *config*'s shell role."""
    if isinstance(agent_family_role, str) and agent_family_role.strip():
        return agent_family_role.strip() == config.family_role
    return agent_family_role_for_suffix(role_suffix) == config.family_role


def is_real_shell_member(
    agent_family_role: str | None,
    shell_id: str | None,
    *,
    config: ShellStateConfig,
) -> bool:
    """Return whether a row is the durable member for this shell kind."""
    return (
        isinstance(agent_family_role, str)
        and agent_family_role.strip() == config.family_role
        and isinstance(shell_id, str)
        and bool(shell_id.strip())
    )


__all__ = [
    "ShellStateConfig",
    "is_real_shell_member",
    "is_shell_member_role",
    "shell_state_bucket",
    "shell_state_is_terminal",
]
