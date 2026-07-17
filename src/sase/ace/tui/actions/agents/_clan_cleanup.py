"""Shared clan-membership helpers for kill and dismissal cascades."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


def clan_members_for_container(
    container: Agent,
    agents_with_children: list[Agent],
) -> list[Agent]:
    """Return live members for a synthetic clan container's generation.

    Killing an ordinary member must leave its siblings alone, so only a
    rootless synthetic row (no artifact suffix) activates the new cascade.
    The legacy branch preserves archived parallel-family root behavior.
    """
    if container.agent_clan and container.raw_suffix is None:
        return [
            candidate
            for candidate in agents_with_children
            if candidate.identity != container.identity
            and candidate.agent_clan == container.agent_clan
            and (
                container.agent_clan_generation is None
                or candidate.agent_clan_generation == container.agent_clan_generation
            )
            and candidate.parent_workflow is None
        ]
    if (
        container.is_workflow_child
        or not container.agent_family_parallel
        or container.raw_suffix is None
    ):
        return []
    return [
        candidate
        for candidate in agents_with_children
        if candidate.identity != container.identity
        and candidate.agent_family_parallel
        and candidate.parent_workflow is None
        and candidate.parent_timestamp == container.raw_suffix
    ]


__all__ = ["clan_members_for_container"]
