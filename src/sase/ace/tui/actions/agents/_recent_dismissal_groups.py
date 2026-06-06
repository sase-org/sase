"""Recent dismissed-agent group cache helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupWire,
    saved_agent_group_summary_from_group,
)

from ._saved_group_records import build_saved_agent_group

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

AgentIdentity = tuple["AgentType", str, str | None]
RECENT_DISMISSAL_LIMIT = 10


def agents_for_recent_group(
    identities: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
) -> list[Agent]:
    """Return snapshot rows matching dismissed identities in row order."""

    if not identities:
        return []
    agents: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for agent in agents_with_children_snapshot:
        if agent.identity not in identities or agent.identity in seen:
            continue
        agents.append(agent)
        seen.add(agent.identity)
    return agents


def build_recent_dismissed_agent_group(
    agents: list[Agent],
) -> SavedAgentGroupWire | None:
    if not agents:
        return None
    return build_saved_agent_group(agents, source="recent_dismissal")


def cache_recent_dismissed_agent_group(
    owner: object,
    group: SavedAgentGroupWire | None,
    *,
    limit: int = RECENT_DISMISSAL_LIMIT,
) -> None:
    if group is None:
        return
    current = list(getattr(owner, "_recent_dismissed_agent_groups", ()))
    owner._recent_dismissed_agent_groups = merge_recent_dismissed_agent_groups(  # type: ignore[attr-defined]
        [group, *current],
        limit=limit,
    )


def merge_recent_dismissed_agent_groups(
    groups: list[SavedAgentGroupWire] | tuple[SavedAgentGroupWire, ...],
    *,
    limit: int = RECENT_DISMISSAL_LIMIT,
) -> list[SavedAgentGroupWire]:
    by_id: dict[str, SavedAgentGroupWire] = {}
    for group in groups:
        if group.group_id in by_id:
            continue
        by_id[group.group_id] = group
    merged = list(by_id.values())
    merged.sort(key=lambda group: group.group_id)
    merged.sort(key=lambda group: group.created_at, reverse=True)
    return merged[: max(1, limit)]


def recent_group_page_from_cache(
    owner: object,
    *,
    limit: int = RECENT_DISMISSAL_LIMIT,
) -> SavedAgentGroupPageWire:
    groups = merge_recent_dismissed_agent_groups(
        tuple(getattr(owner, "_recent_dismissed_agent_groups", ())),
        limit=limit,
    )
    owner._recent_dismissed_agent_groups = groups  # type: ignore[attr-defined]
    return SavedAgentGroupPageWire(
        groups=tuple(saved_agent_group_summary_from_group(group) for group in groups),
        next_cursor=None,
    )


def load_recent_group_from_cache(
    owner: object,
    group_id: str,
) -> SavedAgentGroupWire | None:
    for group in getattr(owner, "_recent_dismissed_agent_groups", ()):
        if group.group_id == group_id:
            return group
    return None


def mark_recent_group_revived_in_cache(
    owner: object,
    group_id: str,
    *,
    revived_at: str,
) -> None:
    groups = []
    for group in getattr(owner, "_recent_dismissed_agent_groups", ()):
        if group.group_id == group_id:
            groups.append(
                replace(
                    group,
                    revived_at=revived_at,
                    times_revived=max(0, group.times_revived) + 1,
                )
            )
        else:
            groups.append(group)
    owner._recent_dismissed_agent_groups = groups  # type: ignore[attr-defined]
