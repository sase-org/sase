"""Presentation-neutral agent status grouping helpers for integrations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sase.agent.running import RunningAgentInfo
from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    AGENT_STATUS_BUCKETS,
    status_bucket_for_values,
)

__all__ = [
    "AgentStatusGroup",
    "agent_status_bucket",
    "agent_status_bucket_glyph",
    "group_agent_statuses",
    "status_bucket_header",
]


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class AgentStatusGroup:
    """A non-empty status bucket and its agents in original order."""

    bucket: str
    agents: list[RunningAgentInfo]


def agent_status_bucket(info: RunningAgentInfo) -> str:
    """Return the shared Agents-tab status bucket for a running-agent record."""
    status = info.status if isinstance(info.status, str) else None
    retried_as_timestamp = getattr(info, "retried_as_timestamp", None)
    if not isinstance(retried_as_timestamp, str):
        retried_as_timestamp = None
    return status_bucket_for_values(status, retried_as_timestamp)


# pyvision: public_api_methods.txt
def agent_status_bucket_glyph(bucket: str) -> str:
    """Return the shared glyph for a status bucket."""
    return AGENT_STATUS_BUCKET_GLYPHS.get(bucket, "")


def group_agent_statuses(
    agents: Iterable[RunningAgentInfo],
) -> list[AgentStatusGroup]:
    """Group agents by shared status buckets, preserving per-bucket order."""
    buckets: dict[str, list[RunningAgentInfo]] = {
        bucket: [] for bucket in AGENT_STATUS_BUCKETS
    }
    for agent in agents:
        buckets[agent_status_bucket(agent)].append(agent)

    return [
        AgentStatusGroup(bucket=bucket, agents=buckets[bucket])
        for bucket in AGENT_STATUS_BUCKETS
        if buckets[bucket]
    ]


# pyvision: public_api_methods.txt
def status_bucket_header(bucket: str, count: int) -> str:
    """Return the shared plain-text status bucket header."""
    glyph = agent_status_bucket_glyph(bucket)
    prefix = f"{glyph} " if glyph else ""
    return f"{prefix}{bucket} ({count})"
