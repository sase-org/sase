"""Compatibility aliases for the renamed clan aggregation module."""

from ._agent_clan import (
    ClanStatusCounts as ParallelAgentSessionStatusCounts,
    agent_summary_status_counts,
    aggregate_clan_status as aggregate_parallel_agent_session_status,
    clan_member_counts as parallel_agent_session_member_counts,
    clan_members as parallel_agent_session_members,
)

__all__ = [
    "ParallelAgentSessionStatusCounts",
    "agent_summary_status_counts",
    "aggregate_parallel_agent_session_status",
    "parallel_agent_session_member_counts",
    "parallel_agent_session_members",
]
