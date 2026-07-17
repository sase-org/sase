"""Cached Agents-tab neighbor index helpers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._fold_scope import panel_fold_registry, panel_fold_version_signature
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.agent_hoods import AgentNeighborIndex, AgentNeighborRow
    from ...models.agent_panels import AgentPanelGroup
    from ...modals.agent_neighbor_modal import AgentNeighborChoice


@dataclass(frozen=True)
class _AgentNeighborPayload:
    """Action payload parallel to one modal choice row."""

    global_idx: int | None = None
    dismissed_agent: Agent | None = None


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
        """Return the neighbor index for all currently visible agent rows."""
        from ...models.agent_groups import GroupingMode

        panel_group = getattr(self, "_panel_group", None)
        panel_keys = tuple(getattr(panel_group, "panel_keys", (None,)))
        fold_version = panel_fold_version_signature(self, panel_keys)
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        dismiss_epoch = getattr(self, "_dismiss_revive_epoch", 0)

        cached = getattr(self, "_agent_neighbor_index_cache", None)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == panel_keys
            and cached[2] == merge_tag_panels
            and cached[3] == grouping_mode
            and cached[4] == fold_version
            and cached[5] == dismiss_epoch
        ):
            return cached[6]

        index = self._build_agent_neighbor_index()
        self._agent_neighbor_index_cache = (
            self._agents,
            panel_keys,
            merge_tag_panels,
            grouping_mode,
            fold_version,
            dismiss_epoch,
            index,
        )
        return index

    def _build_agent_neighbor_index(self) -> AgentNeighborIndex:
        """Build a fresh neighbor index by walking rendered rows."""
        from ...models.agent_hoods import AgentNeighborIndex

        return AgentNeighborIndex.from_visible_rows(
            list(self._visible_agent_neighbor_rows()),
            dismissed_agents=self._active_dismissed_agent_objects(),
        )

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
                    )
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
                    )

    def _start_agent_neighbor_navigation(self) -> None:
        """Jump to, revive, or choose from related agents of the selected agent."""
        if getattr(self, "current_tab", None) != "agents":
            return
        if getattr(self, "_current_group_key", None) is not None:
            return
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return

        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return

        index = self._agent_neighbor_index()
        ancestors = index.ancestors_for(self.current_idx)
        neighbors = index.neighbors_for(self.current_idx)
        descendants = index.descendants_for(self.current_idx)
        dismissed_descendants = self._dismissed_descendant_agents(selected)
        if (
            not ancestors
            and not neighbors
            and not descendants
            and not dismissed_descendants
        ):
            return

        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return

        related_count = (
            len(ancestors)
            + len(neighbors)
            + len(descendants)
            + len(dismissed_descendants)
        )
        if related_count == 1 and not dismissed_descendants:
            target_idx = (
                ancestors[0]
                if ancestors
                else descendants[0]
                if descendants
                else neighbors[0]
            )
            self._focus_agent_neighbor_by_global_index(
                target_idx,
                neighbor_index=index,
            )
            return

        choices, payloads = self._agent_neighbor_choices(
            ancestors,
            descendants,
            dismissed_descendants,
            neighbors,
            index,
        )
        if not choices:
            return

        from ...modals import AgentNeighborModal

        def _on_neighbor_selected(choice_idx: int | None) -> None:
            if choice_idx is None or not 0 <= choice_idx < len(payloads):
                return
            payload = payloads[choice_idx]
            if payload.global_idx is not None:
                self._focus_agent_neighbor_by_global_index(payload.global_idx)
                return
            if payload.dismissed_agent is not None:
                revive = getattr(self, "_do_revive_agent", None)
                if callable(revive):
                    revive(payload.dismissed_agent)

        self.push_screen(  # type: ignore[attr-defined]
            AgentNeighborModal(
                selected.agent_name or selected.display_name,
                choices,
                hood_label=self._agent_neighbor_hood_label(selected),
            ),
            _on_neighbor_selected,
        )

    def _focus_agent_neighbor_by_global_index(
        self,
        target_idx: int,
        *,
        neighbor_index: AgentNeighborIndex | None = None,
    ) -> bool:
        """Focus the visible neighbor row identified by its global agent index."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        if not (0 <= target_idx < len(self._agents)):
            return False

        index = (
            neighbor_index
            if neighbor_index is not None
            else self._agent_neighbor_index()
        )
        target_panel_idx = index.panel_idx_for(target_idx)
        if target_panel_idx is None:
            return False

        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None and not (
            0 <= target_panel_idx < len(panel_group.panel_keys)
        ):
            return False
        if panel_group is None and target_panel_idx != 0:
            return False

        old_focused_idx = panel_group.focused_idx if panel_group is not None else None
        old_idx = self.current_idx
        old_group_key = getattr(self, "_current_group_key", None)
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )
        focus_will_change = (
            old_idx != target_idx
            or old_group_key is not None
            or (old_focused_idx is not None and target_panel_idx != old_focused_idx)
        )
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if focus_will_change and callable(save_jump_anchor):
            save_jump_anchor()

        if (
            panel_group is not None
            and 0 <= target_panel_idx < len(panel_group.panel_keys)
            and target_panel_idx != panel_group.focused_idx
        ):
            panel_group.focused_idx = target_panel_idx

        if old_agent is not None and old_idx != target_idx:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        self._current_group_key = None  # type: ignore[attr-defined]
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]
        self.current_idx = target_idx

        target_agent = self._agents[target_idx]
        ack_unread = getattr(self, "_acknowledge_agent_unread", None)
        if callable(ack_unread):
            ack_unread(target_agent)

        self._refresh_agent_neighbor_jump_views(old_focused_idx=old_focused_idx)
        return True

    def _refresh_agent_neighbor_jump_views(
        self, *, old_focused_idx: int | None
    ) -> None:
        """Refresh selection chrome after a neighbor jump without rebuilding rows."""
        panel_group = getattr(self, "_panel_group", None)
        focused_changed = (
            panel_group is not None
            and old_focused_idx is not None
            and old_focused_idx != panel_group.focused_idx
        )
        refresh_focused_panel = getattr(self, "_refresh_focused_agent_panel", None)
        if focused_changed and callable(refresh_focused_panel):
            refresh_focused_panel(old_focused_idx=old_focused_idx)
        else:
            refresh_highlights = getattr(self, "_refresh_panel_highlights", None)
            if callable(refresh_highlights):
                refresh_highlights()
            else:
                refresh_display = getattr(self, "_refresh_agents_display", None)
                if callable(refresh_display):
                    refresh_display(list_changed=False)

        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        apply_immediate = getattr(self, "_apply_agent_detail_immediate", None)
        if callable(apply_immediate):
            apply_immediate()
        debouncer = getattr(self, "_agent_detail_debouncer", None)
        fire_detail = getattr(self, "_fire_debounced_detail_update", None)
        if debouncer is not None and callable(fire_detail):
            debouncer.schedule(fire_detail)

    def _agent_neighbor_choices(
        self,
        ancestors: tuple[int, ...],
        descendants: tuple[int, ...],
        dismissed_descendants: tuple[Agent, ...],
        neighbors: tuple[int, ...],
        index: AgentNeighborIndex,
    ) -> tuple[list[AgentNeighborChoice], list[_AgentNeighborPayload]]:
        """Build modal choices and action payloads for related rows."""
        from ...models.agent_hoods import agent_name_key
        from ...modals.agent_neighbor_modal import AgentNeighborChoice

        choices: list[AgentNeighborChoice] = []
        payloads: list[_AgentNeighborPayload] = []

        for global_idx in ancestors:
            if not (0 <= global_idx < len(self._agents)):
                continue
            agent = self._agents[global_idx]
            choices.append(
                AgentNeighborChoice(
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=self._agent_neighbor_panel_label(
                        index.panel_idx_for(global_idx)
                    ),
                    time_hint=self._agent_neighbor_time_hint(agent),
                    group="ancestor",
                    dismissed=False,
                    global_idx=global_idx,
                )
            )
            payloads.append(_AgentNeighborPayload(global_idx=global_idx))

        descendant_items: list[tuple[str, bool, Agent, int | None]] = []
        for global_idx in descendants:
            if not (0 <= global_idx < len(self._agents)):
                continue
            agent = self._agents[global_idx]
            key = agent_name_key(agent)
            if key is None:
                continue
            descendant_items.append((key, False, agent, global_idx))
        for agent in dismissed_descendants:
            key = agent_name_key(agent)
            if key is None:
                continue
            descendant_items.append((key, True, agent, None))

        for _key, dismissed, agent, descendant_global_idx in sorted(
            descendant_items,
            key=lambda item: (
                item[0],
                item[1],
                (item[2].display_name or "").casefold(),
            ),
        ):
            choices.append(
                AgentNeighborChoice(
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=(
                        self._agent_neighbor_dismissed_panel_label(agent)
                        if dismissed
                        else self._agent_neighbor_panel_label(
                            index.panel_idx_for(descendant_global_idx)
                            if descendant_global_idx is not None
                            else None
                        )
                    ),
                    time_hint=self._agent_neighbor_time_hint(agent),
                    group="descendant",
                    dismissed=dismissed,
                    global_idx=descendant_global_idx,
                )
            )
            payloads.append(
                _AgentNeighborPayload(
                    global_idx=descendant_global_idx,
                    dismissed_agent=agent if dismissed else None,
                )
            )

        for global_idx in neighbors:
            if not (0 <= global_idx < len(self._agents)):
                continue
            agent = self._agents[global_idx]
            choices.append(
                AgentNeighborChoice(
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=self._agent_neighbor_panel_label(
                        index.panel_idx_for(global_idx)
                    ),
                    time_hint=self._agent_neighbor_time_hint(agent),
                    group="neighbor",
                    dismissed=False,
                    global_idx=global_idx,
                )
            )
            payloads.append(_AgentNeighborPayload(global_idx=global_idx))
        return choices, payloads

    def _dismissed_descendant_agents(self, selected: Agent) -> tuple[Agent, ...]:
        """Return active dismissed descendants of ``selected`` sorted by name."""
        from ...models.agent_hoods import agent_name_key, is_agent_descendant

        selected_name = selected.agent_name
        if selected_name is None:
            return ()

        descendants = [
            agent
            for agent in self._active_dismissed_agent_objects()
            if is_agent_descendant(agent.agent_name, selected_name)
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

    def _agent_neighbor_hood_label(self, agent: Agent) -> str:
        """Return the display hood label used by the chooser title."""
        name = agent.agent_name or ""
        hood, _, last = name.rpartition(".")
        return hood if hood and last else "agent"

    def _agent_neighbor_panel_label(self, panel_idx: int | None) -> str:
        """Return a compact label for the tag panel containing a neighbor."""
        if getattr(self, "_agent_panels_grouped", False):
            return "all"
        panel_group = getattr(self, "_panel_group", None)
        if (
            panel_group is None
            or panel_idx is None
            or not (0 <= panel_idx < len(panel_group.panel_keys))
        ):
            return "panel"
        key = panel_group.panel_keys[panel_idx]
        return "(untagged)" if key is None else f"@{key}"

    def _agent_neighbor_dismissed_panel_label(self, agent: Agent) -> str:
        """Return a compact tag label for a dismissed descendant row."""
        if getattr(self, "_agent_panels_grouped", False):
            return "all"
        tag = getattr(agent, "tag", None)
        return f"@{tag}" if tag else "(untagged)"

    def _agent_neighbor_time_hint(self, agent: Agent) -> str:
        """Return a compact timestamp/runtime hint for a neighbor row."""
        from ...models.agent import compute_row_runtime

        timestamp, elapsed = compute_row_runtime(agent)
        if timestamp is not None:
            date_prefix, time_text = timestamp
            finished = f"{date_prefix}{time_text}".strip()
            return f"{finished} {elapsed or ''}".strip()
        if elapsed:
            return elapsed
        if agent.stop_time is not None:
            return agent.stop_time.strftime("%H:%M")
        if agent.run_start_time is not None:
            return agent.run_start_time.strftime("%H:%M")
        if agent.start_time is not None:
            return agent.start_time.strftime("%H:%M")
        return ""
