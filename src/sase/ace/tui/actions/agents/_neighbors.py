"""Cached Agents-tab neighbor index helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ._fold_scope import panel_fold_registry, panel_fold_version_signature
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import effective_panel_collapses

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.agent_hoods import AgentNeighborIndex, AgentNeighborRow
    from ...models.sase_agent_neighbors import SaseAgentNeighborProjection
    from ...models.agent_panels import AgentPanelGroup


class AgentNeighborMixin:
    """Mixin that exposes the cached visible neighbor index."""

    _agents: list[Agent]
    _dismissed_agents: set[Any]
    _dismissed_agent_objects: list[Agent]
    _dismiss_revive_epoch: int
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _agent_neighbor_index_cache: tuple[Any, ...] | None
    _current_group_key: tuple[str, ...] | None
    current_idx: int
    current_attempt_number: int | None
    current_tab: str

    def _agent_neighbor_index(self) -> AgentNeighborIndex:
        """Return the cached index of rendered and clan-revealable rows."""
        from ...models.agent_groups import GroupingMode

        panel_group = getattr(self, "_panel_group", None)
        panel_keys = tuple(getattr(panel_group, "panel_keys", (None,)))
        fold_version = panel_fold_version_signature(self, panel_keys)
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        dismiss_epoch = getattr(self, "_dismiss_revive_epoch", 0)
        complete = list(getattr(self, "_agents_with_children", ()) or self._agents)
        fold_manager = getattr(self, "_fold_manager", None)
        tree_fold_signature = (
            tuple(
                sorted(
                    (key, level.value) for key, level in fold_manager.snapshot().items()
                )
            )
            if fold_manager is not None
            else ()
        )
        roster_signature = tuple(
            (
                agent.identity,
                agent.agent_name,
                agent.status,
                agent.tribe,
                agent.project_file,
                agent.tree_parent_key,
                agent.is_hidden_step,
                agent.is_clan_container,
                tuple(child.identity for child in agent.runtime_children),
            )
            for agent in complete
        )
        current_signature = tuple(agent.identity for agent in self._agents)
        query_signature = (
            getattr(self, "_agent_search_query", "") or "",
            id(getattr(self, "_agents_live_query_facade", None)),
            id(getattr(self, "_agent_content_search_index", None)),
        )
        dismissed_signature = (
            dismiss_epoch,
            frozenset(getattr(self, "_dismissed_agents", set())),
        )
        panel_collapse_signature = frozenset(
            effective_panel_collapses(
                self, getattr(self._panel_group, "panel_keys", ())
            )
        )

        cached = getattr(self, "_agent_neighbor_index_cache", None)
        if (
            cached is not None
            and cached[0] == current_signature
            and cached[1] == roster_signature
            and cached[2] == panel_keys
            and cached[3] == merge_tribe_panels
            and cached[4] == grouping_mode
            and cached[5] == fold_version
            and cached[6] == tree_fold_signature
            and cached[7] == query_signature
            and cached[8] == dismissed_signature
            and cached[9] == panel_collapse_signature
        ):
            return cached[10]

        index = self._build_agent_neighbor_index()
        self._agent_neighbor_index_cache = (
            current_signature,
            roster_signature,
            panel_keys,
            merge_tribe_panels,
            grouping_mode,
            fold_version,
            tree_fold_signature,
            query_signature,
            dismissed_signature,
            panel_collapse_signature,
            index,
        )
        return index

    def _build_agent_neighbor_index(self) -> AgentNeighborIndex:
        """Build a fresh neighbor index from rendered and prospective rows."""
        from ...models.agent_hoods import AgentNeighborIndex

        return AgentNeighborIndex.from_visible_rows(
            list(self._revealable_agent_neighbor_rows()),
            dismissed_agents=self._active_dismissed_agent_objects(),
        )

    def _revealable_agent_neighbor_rows(self) -> Iterator[AgentNeighborRow]:
        """Yield the rendered union plus rows hidden only by clan folding."""
        from ...models.agent_hoods import AgentNeighborRow, agent_hood
        from ._prospective_clan import prospective_clan_projection

        visible = list(self._visible_agent_neighbor_rows())
        complete = list(getattr(self, "_agents_with_children", ()) or self._agents)
        projection = prospective_clan_projection(self, complete)
        visible_identities = {row.identity for row in visible}
        rows: list[AgentNeighborRow] = []
        fallback_offset = len(projection.display_order_by_identity)
        for fallback_order, row in enumerate(visible):
            rows.append(
                AgentNeighborRow(
                    global_idx=row.global_idx,
                    panel_idx=row.panel_idx,
                    agent=row.agent,
                    hood=row.hood,
                    panel_key=row.panel_key,
                    display_order=projection.display_order_by_identity.get(
                        row.identity,
                        fallback_offset + fallback_order,
                    ),
                )
            )
        for target in projection.members.values():
            if target.identity in visible_identities:
                continue
            rows.append(
                AgentNeighborRow(
                    global_idx=None,
                    panel_idx=target.panel_idx,
                    panel_key=target.panel_key,
                    agent=target.agent,
                    hood=agent_hood(target.agent),
                    display_order=target.display_order,
                    clan_fold_key=target.clan_fold_key,
                )
            )
        yield from sorted(rows, key=lambda row: row.display_order)

    def _active_dismissed_agent_objects(self) -> tuple[Agent, ...]:
        """Return same-session dismissed objects whose identities are still hidden."""
        dismissed_ids: set[Any] = set(getattr(self, "_dismissed_agents", set()))
        if not dismissed_ids:
            return ()

        active: list[Agent] = []
        seen: set[Any] = set()
        for agent in getattr(self, "_dismissed_agent_objects", ()):
            identity = agent.identity
            if identity in seen or identity not in dismissed_ids:
                continue
            active.append(agent)
            seen.add(identity)
        return tuple(active)

    def _visible_agent_neighbor_rows(self) -> Iterator[AgentNeighborRow]:
        """Yield visible agent rows across every rendered Agents-tab panel."""
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_hoods import AgentNeighborRow, agent_hood
        from ...models.agent_panels import agent_is_rendered_in_agents_panel

        mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        display_order = 0

        if panel_group is None:
            registry = panel_fold_registry(self, None)
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
                    yield AgentNeighborRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=0,
                        agent=panel_agents[local_idx],
                        hood=agent_hood(panel_agents[local_idx]),
                        panel_key=None,
                        display_order=display_order,
                    )
                    display_order += 1
            return

        for panel_idx, key in enumerate(panel_group.panel_keys):
            registry = panel_fold_registry(self, key)
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "agent" and entry.agent_idx is not None:
                    local_idx = entry.agent_idx
                    yield AgentNeighborRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=panel_idx,
                        agent=panel_agents[local_idx],
                        hood=agent_hood(panel_agents[local_idx]),
                        panel_key=key,
                        display_order=display_order,
                    )
                    display_order += 1

    def lane_neighbor_projection_for(
        self,
        agent: Agent,
    ) -> SaseAgentNeighborProjection | None:
        """Return the lane-relative neighbor projection for a lane-owning row."""
        from ...models.agent_family_members import concrete_family_shell_rows
        from ...models.agent_hoods import sase_agent_name, agent_owns_sase_agent
        from ...models.sase_agent_neighbors import (
            build_sase_agent_neighbor_projection,
        )

        if not agent_owns_sase_agent(agent):
            return None

        suppressed_identities = (
            {member.identity for member in concrete_family_shell_rows(agent)}
            if agent.is_family_container_row
            else ()
        )
        return build_sase_agent_neighbor_projection(
            lane_identity=agent.identity,
            lane_name=sase_agent_name(agent),
            lane_row_names=(agent.presented_identity_name or "",),
            index=self._agent_neighbor_index(),
            dismissed_descendants=self._dismissed_descendant_agents(agent),
            suppressed_identities=suppressed_identities,
            hood_labels=self._agent_neighbor_display_hoods(agent),
        )

    def _dismissed_descendant_agents(self, selected: Agent) -> tuple[Agent, ...]:
        """Return active dismissed descendants of ``selected`` sorted by name."""
        from ...models.agent_hoods import (
            sase_agent_name,
            agent_name_key,
            is_agent_descendant,
        )

        selected_name = sase_agent_name(selected)
        if selected_name is None:
            return ()

        descendants = [
            agent
            for agent in self._active_dismissed_agent_objects()
            if is_agent_descendant(agent.presented_identity_name, selected_name)
        ]
        return tuple(
            sorted(
                descendants,
                key=lambda agent: (
                    agent_name_key(agent) or "",
                    (agent.display_name or "").casefold(),
                ),
            )
        )

    def _agent_neighbor_display_hoods(self, agent: Agent) -> dict[str, str]:
        """Map selected-agent hood keys to labels preserving displayed case."""
        from ...models.agent_hoods import sase_agent_name

        parts = (sase_agent_name(agent) or "").split(".")
        return {
            ".".join(parts[:depth]).casefold(): ".".join(parts[:depth])
            for depth in range(1, len(parts) + 1)
            if all(parts[:depth])
        }
