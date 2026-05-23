"""Cached Agents-tab sibling index helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.agent_panels import AgentPanelGroup
    from ...models.agent_siblings import AgentSiblingIndex, AgentSiblingRow


class AgentSiblingMixin:
    """Mixin that exposes the cached visible sibling index."""

    _agents: list[Agent]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _agent_sibling_index_cache: tuple[Any, ...] | None

    def _agent_sibling_index(self) -> AgentSiblingIndex:
        """Return the sibling index for all currently visible agent rows."""
        from ...models.agent_groups import GroupingMode

        panel_group = getattr(self, "_panel_group", None)
        panel_keys = tuple(getattr(panel_group, "panel_keys", (None,)))
        registry = getattr(self, "_group_fold_registry", None)
        fold_version = getattr(registry, "version", 0)
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)

        cached = getattr(self, "_agent_sibling_index_cache", None)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == panel_keys
            and cached[2] == merge_tag_panels
            and cached[3] == grouping_mode
            and cached[4] == fold_version
        ):
            return cached[5]

        index = self._build_agent_sibling_index()
        self._agent_sibling_index_cache = (
            self._agents,
            panel_keys,
            merge_tag_panels,
            grouping_mode,
            fold_version,
            index,
        )
        return index

    def _build_agent_sibling_index(self) -> AgentSiblingIndex:
        """Build a fresh sibling index by walking rendered rows."""
        from ...models.agent_siblings import AgentSiblingIndex

        return AgentSiblingIndex.from_visible_rows(
            list(self._visible_agent_sibling_rows())
        )

    def _visible_agent_sibling_rows(self) -> Iterator[AgentSiblingRow]:
        """Yield visible agent rows across every rendered Agents-tab panel."""
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import agent_is_rendered_in_agents_panel
        from ...models.agent_siblings import AgentSiblingRow, agent_sibling_family

        registry = getattr(self, "_group_fold_registry", None)
        mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)

        if panel_group is None:
            global_indices = [
                idx
                for idx, agent in enumerate(self._agents)
                if agent_is_rendered_in_agents_panel(agent)
            ]
            panel_agents = [self._agents[idx] for idx in global_indices]
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "agent" and entry.agent_idx is not None:
                    local_idx = entry.agent_idx
                    yield AgentSiblingRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=0,
                        agent=panel_agents[local_idx],
                        family=agent_sibling_family(panel_agents[local_idx]),
                    )
            return

        for panel_idx, key in enumerate(panel_group.panel_keys):
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "agent" and entry.agent_idx is not None:
                    local_idx = entry.agent_idx
                    yield AgentSiblingRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=panel_idx,
                        agent=panel_agents[local_idx],
                        family=agent_sibling_family(panel_agents[local_idx]),
                    )
