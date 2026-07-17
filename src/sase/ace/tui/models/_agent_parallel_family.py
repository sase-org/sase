"""Compatibility aliases for the renamed clan aggregation module."""

from ._agent_clan import (
    ClanStatusCounts as ParallelFamilyStatusCounts,
    agent_summary_status_counts,
    aggregate_clan_status as aggregate_parallel_family_status,
    clan_member_counts as parallel_family_member_counts,
    clan_members as parallel_family_members,
)

__all__ = [
    "ParallelFamilyStatusCounts",
    "agent_summary_status_counts",
    "aggregate_parallel_family_status",
    "parallel_family_member_counts",
    "parallel_family_members",
]
