"""Continuation-handshake selection for foreground ToolRun execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.tool._executor_shared import default_continuation_mode

if TYPE_CHECKING:
    from sase.tool.argv import ResolvedToolArgv


def agent_default_continuation_mode(
    resolved: ResolvedToolArgv, agent: str | None
) -> str | None:
    """Return the handshake mode for a recorded run with *agent* attribution.

    An agent-attributed run of a ``stages: run_silent`` named tool continues
    past all-KNOWN/FLAKY stages; every other run keeps fail-fast. Adopted
    monitor workers pass the run's stored agent so a starter-agent reservation
    inherits the same default through its recorded attribution.
    """

    default_mode = default_continuation_mode(resolved)
    if default_mode is None:
        return None
    if agent and agent.strip():
        return "known"
    return default_mode


__all__ = ["agent_default_continuation_mode"]
