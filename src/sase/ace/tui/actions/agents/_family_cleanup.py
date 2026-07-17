"""Shared family-membership helpers for kill and dismissal cascades."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


def parallel_family_members_for_root(
    root: Agent,
    agents_with_children: list[Agent],
) -> list[Agent]:
    """Return parallel members linked to ``root``'s exact generation.

    Both the root and member marker are required so serial plan-chain children
    retain their historical non-cascading behavior.
    """
    if (
        root.is_workflow_child
        or not root.agent_family_parallel
        or root.raw_suffix is None
    ):
        return []
    return [
        candidate
        for candidate in agents_with_children
        if candidate.identity != root.identity
        and candidate.agent_family_parallel
        and candidate.parent_workflow is None
        and candidate.parent_timestamp == root.raw_suffix
    ]


__all__ = ["parallel_family_members_for_root"]
