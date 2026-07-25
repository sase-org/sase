"""Shared in-memory digest helpers for agent member rosters."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ...models.agent_time import compute_row_runtime

if TYPE_CHECKING:
    from ...models.agent import Agent


@dataclass(frozen=True, slots=True)
class _AgentRosterDigest:
    """In-memory agent facts consumed by the shared roster renderer."""

    activity: str | None
    waiting: tuple[str, ...]
    retry: tuple[str, ...]
    workspace_num: int | None
    start_time: datetime | None
    run_start_time: datetime | None
    stop_time: datetime | None
    attempt_count: int
    extra_annotations: tuple[str, ...] = ()


def agent_roster_digest(
    agent: Agent,
    *,
    extra_annotations: tuple[str, ...] = (),
) -> _AgentRosterDigest:
    """Build the shared in-memory roster digest for one agent."""
    return _AgentRosterDigest(
        activity=agent.activity,
        waiting=_waiting_digest(agent),
        retry=_retry_digest(agent),
        workspace_num=agent.effective_workspace_num,
        start_time=agent.start_time,
        run_start_time=agent.run_start_time,
        stop_time=agent.stop_time,
        attempt_count=len(agent.attempt_history),
        extra_annotations=extra_annotations,
    )


def agent_roster_duration(agent: Agent, *, now: datetime | None = None) -> str:
    """Return the leaf runtime rendered by numbered agent rosters."""
    leaf = agent
    if agent.runtime_children:
        leaf = copy(agent)
        leaf.runtime_children = []
    _timestamp, elapsed = compute_row_runtime(leaf, now=now)
    return elapsed or "—"


def _waiting_digest(agent: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if agent.waiting_for:
        parts.append("for " + ", ".join(agent.waiting_for))
    if agent.waiting_for_beads:
        parts.append("for beads " + ", ".join(agent.waiting_for_beads))
    if agent.wait_duration is not None:
        parts.append(f"{agent.wait_duration:g}s")
    if agent.wait_until:
        parts.append(f"until {agent.wait_until}")
    if agent.wait_runners is not None:
        parts.append(f"runners≤{agent.wait_runners}")
    return tuple(parts)


def _retry_digest(agent: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if agent.retry_count or agent.max_retries:
        parts.append(f"{agent.retry_count}/{agent.max_retries}")
    if agent.retry_status:
        parts.append(agent.retry_status.replace("_", " "))
    if agent.using_fallback:
        parts.append(f"via {agent.fallback_model or 'fallback'}")
    return tuple(parts)


__all__ = [
    "agent_roster_digest",
    "agent_roster_duration",
]
