"""Shared helpers for focused agent-group banner actions."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_groups import GroupRow


def get_focused_agent_group(owner: Any) -> GroupRow | None:
    """Return the focused panel's group with global agent indices."""
    from ...models.agent_groups import GroupingMode, build_agent_tree
    from ...models.agent_panels import agent_is_rendered_in_agents_panel

    current_group_key = getattr(owner, "_current_group_key", None)
    agents = getattr(owner, "_agents", None)
    if current_group_key is None or not agents:
        return None

    panel_group = getattr(owner, "_panel_group", None)
    if panel_group is None:
        global_indices = [
            i
            for i, agent in enumerate(agents)
            if agent_is_rendered_in_agents_panel(agent)
        ]
        panel_agents = [agents[i] for i in global_indices]
    else:
        from ._navigation_order import rendered_panel_slice

        global_indices, panel_agents = rendered_panel_slice(
            owner, panel_group.focused_key
        )

    registry = getattr(owner, "_group_fold_registry", None)
    mode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    for entry in build_agent_tree(panel_agents, fold_registry=registry, mode=mode):
        if entry.kind != "group" or entry.group is None:
            continue
        if entry.group.group_key == current_group_key:
            return replace(
                entry.group,
                agent_indices=tuple(
                    global_indices[i]
                    for i in entry.group.agent_indices
                    if 0 <= i < len(global_indices)
                ),
            )
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
