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
    from ...modals.agent_sibling_modal import AgentSiblingChoice


class AgentSiblingMixin:
    """Mixin that exposes the cached visible sibling index."""

    _agents: list[Agent]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _agent_sibling_index_cache: tuple[Any, ...] | None
    _current_group_key: tuple[str, ...] | None
    current_idx: int
    current_attempt_number: int | None
    current_tab: str

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

    def _start_agent_sibling_navigation(self) -> None:
        """Jump to, or choose from, visible siblings of the selected agent."""
        if getattr(self, "current_tab", None) != "agents":
            return
        if getattr(self, "_current_group_key", None) is not None:
            return
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return

        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return

        from ...models.agent_siblings import agent_sibling_family

        if agent_sibling_family(selected) is None:
            return

        index = self._agent_sibling_index()
        siblings = index.siblings_for(self.current_idx)
        if not siblings:
            return

        guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
        if callable(guard) and guard():
            return

        if len(siblings) == 1:
            self._focus_agent_sibling_by_global_index(
                siblings[0],
                sibling_index=index,
            )
            return

        choices = self._agent_sibling_choices(siblings, index)
        if not choices:
            return

        from ...modals import AgentSiblingModal

        def _on_sibling_selected(target_idx: int | None) -> None:
            if target_idx is None:
                return
            self._focus_agent_sibling_by_global_index(target_idx)

        self.push_screen(  # type: ignore[attr-defined]
            AgentSiblingModal(
                self._agent_sibling_family_label(selected),
                choices,
            ),
            _on_sibling_selected,
        )

    def _focus_agent_sibling_by_global_index(
        self,
        target_idx: int,
        *,
        sibling_index: AgentSiblingIndex | None = None,
    ) -> bool:
        """Focus the visible sibling row identified by its global agent index."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        if not (0 <= target_idx < len(self._agents)):
            return False

        index = (
            sibling_index if sibling_index is not None else self._agent_sibling_index()
        )
        target_panel_idx = index.panel_idx_for(target_idx)
        if target_panel_idx is None:
            return False

        guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
        if callable(guard) and guard():
            return False

        panel_group = getattr(self, "_panel_group", None)
        old_focused_idx = panel_group.focused_idx if panel_group is not None else None
        old_idx = self.current_idx
        old_group_key = getattr(self, "_current_group_key", None)
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )

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

        self._refresh_agent_sibling_jump_views(old_focused_idx=old_focused_idx)
        return True

    def _refresh_agent_sibling_jump_views(self, *, old_focused_idx: int | None) -> None:
        """Refresh selection chrome after a sibling jump without rebuilding rows."""
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

    def _agent_sibling_choices(
        self,
        siblings: tuple[int, ...],
        index: AgentSiblingIndex,
    ) -> list[AgentSiblingChoice]:
        """Build modal choices for sibling rows in render order."""
        from ...modals.agent_sibling_modal import AgentSiblingChoice

        choices: list[AgentSiblingChoice] = []
        for global_idx in siblings:
            if not (0 <= global_idx < len(self._agents)):
                continue
            agent = self._agents[global_idx]
            choices.append(
                AgentSiblingChoice(
                    global_idx=global_idx,
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=self._agent_sibling_panel_label(
                        index.panel_idx_for(global_idx)
                    ),
                    time_hint=self._agent_sibling_time_hint(agent),
                )
            )
        return choices

    def _agent_sibling_family_label(self, agent: Agent) -> str:
        """Return the display family label used by the chooser title."""
        name = agent.agent_name or ""
        family = name.split(".", 1)[0] if "." in name else name
        return f"{family}.*" if family else "*"

    def _agent_sibling_panel_label(self, panel_idx: int | None) -> str:
        """Return a compact label for the tag panel containing a sibling."""
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
        return "(untagged)" if key is None else f"#{key}"

    def _agent_sibling_time_hint(self, agent: Agent) -> str:
        """Return a compact timestamp/runtime hint for a sibling row."""
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
