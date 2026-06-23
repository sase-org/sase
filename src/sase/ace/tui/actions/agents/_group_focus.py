"""Shared helpers for focused agent-group banner actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_groups import GroupRow


def get_focused_agent_group(owner: Any) -> GroupRow | None:
    """Return the visible group matching ``owner._current_group_key``."""
    from ...models.agent_groups import GroupingMode, build_agent_tree

    current_group_key = getattr(owner, "_current_group_key", None)
    agents = getattr(owner, "_agents", None)
    if current_group_key is None or not agents:
        return None

    registry = getattr(owner, "_group_fold_registry", None)
    mode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    for entry in build_agent_tree(agents, fold_registry=registry, mode=mode):
        if entry.kind != "group" or entry.group is None:
            continue
        if entry.group.group_key == current_group_key:
            return entry.group
    return None


def top_level_group_agents(group: GroupRow, agents: list[Agent]) -> list[Agent]:
    """Return non-workflow-child agents covered by ``group`` in tree order."""
    members: list[Agent] = []
    for idx in group.agent_indices:
        if not (0 <= idx < len(agents)):
            continue
        agent = agents[idx]
        if agent.is_workflow_child:
            continue
        members.append(agent)
    return members
