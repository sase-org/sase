"""AgentList mounting and selective panel-widget refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import panel_widget_id
from ._display_panel_state import PanelRefreshStateMixin
from ._fold_scope import panel_fold_registry
from ._panel_fold_intent import effective_panel_collapses

if TYPE_CHECKING:
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget


class PanelWidgetRefreshMixin(PanelRefreshStateMixin):
    """Mount, remove, and repaint AgentList panel widgets."""

    def _refresh_panel_widgets(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None = None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
    ) -> None:
        """Mount/unmount AgentList widgets to match :attr:`_panel_group`."""
        with tui_trace(
            "agents.refresh_panel_widgets",
            agents=len(self._agents),
            panels=len(self._panel_group.panel_keys),
        ):
            self._refresh_panel_widgets_impl(
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                panel_jump_hints=panel_jump_hints,
            )

    def _refresh_panel_widgets_impl(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None = None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
    ) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one(  # type: ignore[attr-defined]
                "#agent-list-container"
            )
        except NoMatches:
            return

        panel_keys = self._panel_group.panel_keys
        panel_index = self._agent_panel_index()
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        effective_tribes: list[str] = []
        if merge_tribe_panels:
            from ...models.agent_panels import effective_tribe_per_agent

            effective_tribes = effective_tribe_per_agent(self._agents)

        existing_ids = {w.id for w in container.children if isinstance(w, AgentList)}
        for idx in range(len(panel_keys)):
            wid = panel_widget_id(idx)
            if wid not in existing_ids:
                container.mount(AgentList(id=wid))
                existing_ids.add(wid)

        keep_ids = {panel_widget_id(i) for i in range(len(panel_keys))}
        for w in list(container.children):
            if isinstance(w, AgentList) and w.id not in keep_ids:
                w.remove()

        focused_idx = self._panel_group.focused_idx
        marked = self._marked_agents
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        fold_counts = self._fold_counts
        from ...widgets._agent_list_build import compute_visible_parents

        visible_parent_keys, fully_expanded_parent_keys = compute_visible_parents(
            self._agents
        )
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        isolation_marked_keys = marked_keys_fn() if callable(marked_keys_fn) else set()
        restore_marked_fn = getattr(self, "_panel_fold_restore_marked_keys", None)
        fold_restore_marked = restore_marked_fn() if callable(restore_marked_fn) else {}

        ordered_widgets: list[AgentList] = []
        for idx, key in enumerate(panel_keys):
            wid = panel_widget_id(idx)
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{wid}", AgentList
                )
            except NoMatches:
                continue
            ordered_widgets.append(widget)

            slot = panel_index.slice_for(key)
            panel_agents = slot.agents
            global_indices = slot.global_indices
            global_to_local = slot.global_to_local
            panel_collapsed = key in collapsed_keys
            marked_fold_keys = fold_restore_marked.get(key, ())
            selected_expanded = bool(
                panel_focus is not None
                and not panel_focus.collapsed
                and panel_focus.panel_key == key
            )
            self._set_agent_panel_title(
                widget,
                self._agent_panel_title(
                    key,
                    panel_agents,
                    merge_tribe_panels=merge_tribe_panels,
                    panel_jump_hints=panel_jump_hints,
                    isolation_restore_marked=key in isolation_marked_keys,
                    fold_restore_marked_count=len(marked_fold_keys),
                ),
            )
            if idx == 0:
                widget.remove_class("agent-panel-separated")
            else:
                widget.add_class("agent-panel-separated")

            local_idx = -1
            if (
                idx == focused_idx
                and not selected_expanded
                and 0 <= global_idx < len(self._agents)
            ):
                local_idx = global_to_local.get(global_idx, -1)

            local_jump_hints: dict[int, str] | None = None
            if jump_hints:
                local_jump_hints = {}
                for local_i, gi in enumerate(global_indices):
                    if gi in jump_hints:
                        local_jump_hints[local_i] = jump_hints[gi]

            local_banner_hints: dict[tuple[str, ...], str] | None = None
            if banner_jump_hints:
                local_banner_hints = {
                    group_key: hint
                    for (
                        kind,
                        panel_idx,
                        group_key,
                    ), hint in banner_jump_hints.items()
                    if kind == "banner" and panel_idx == idx
                }
                if not local_banner_hints:
                    local_banner_hints = None

            local_tribe_labels: list[str | None] | None = None
            if merge_tribe_panels:
                local_tribe_labels = [
                    effective_tribes[gi]
                    if 0 <= gi < len(effective_tribes)
                    and effective_tribes[gi] is not None
                    else None
                    for gi in global_indices
                ]

            if panel_collapsed:
                widget.add_class("-collapsed-panel")
                widget.render_collapsed()
            else:
                widget.remove_class("-collapsed-panel")
                widget.update_list(
                    panel_agents,
                    local_idx,
                    fold_counts=fold_counts,
                    marked_agents=marked,
                    unread_agents=unread,
                    fold_restore_marked_keys=marked_fold_keys,
                    jump_hints=local_jump_hints,
                    banner_jump_hints=local_banner_hints,
                    current_attempt_number=(
                        attempt_number if idx == focused_idx else None
                    ),
                    fold_registry=panel_fold_registry(self, key),
                    current_group_key=(
                        current_group_key
                        if idx == focused_idx and not selected_expanded
                        else None
                    ),
                    grouping_mode=grouping_mode,
                    tribe_labels=local_tribe_labels,
                    panel_tribe=key if not merge_tribe_panels else None,
                    parents_with_visible_children=visible_parent_keys,
                    fully_expanded_parents=fully_expanded_parent_keys,
                )

            if idx == focused_idx:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")
            if selected_expanded:
                widget.add_class("-whole-panel-focus")
                widget.clear_highlight()
            else:
                widget.remove_class("-whole-panel-focus")

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()

    def _refresh_affected_panel_widgets(
        self,
        affected_keys: set[PanelKey],
    ) -> bool:
        """Rebuild only rendered panels whose membership/content changed."""
        if not affected_keys:
            return True

        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one(  # type: ignore[attr-defined]
                "#agent-list-container"
            )
        except NoMatches:
            return False

        panel_keys = self._panel_group.panel_keys
        panel_index = self._agent_panel_index()
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        effective_tribes: list[str] = []
        if merge_tribe_panels:
            from ...models.agent_panels import effective_tribe_per_agent

            effective_tribes = effective_tribe_per_agent(self._agents)

        jump_hints = (
            dict(getattr(self, "_entry_jump_index_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        banner_jump_hints = (
            dict(getattr(self, "_entry_jump_banner_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        panel_jump_hints = (
            dict(getattr(self, "_entry_jump_panel_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        if not getattr(self, "_entry_jump_mode_active", False) and getattr(
            self, "_panel_fold_hint_mode_active", False
        ):
            (
                jump_hints,
                banner_jump_hints,
            ) = self._panel_fold_hint_display_maps()  # type: ignore[attr-defined]
            panel_jump_hints = None

        focused_idx = self._panel_group.focused_idx
        marked = self._marked_agents
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        fold_counts = self._fold_counts
        from ...widgets._agent_list_build import compute_visible_parents

        visible_parent_keys, fully_expanded_parent_keys = compute_visible_parents(
            self._agents
        )
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        isolation_marked_keys = marked_keys_fn() if callable(marked_keys_fn) else set()
        restore_marked_fn = getattr(self, "_panel_fold_restore_marked_keys", None)
        fold_restore_marked = restore_marked_fn() if callable(restore_marked_fn) else {}

        ordered_widgets: list[AgentList] = []
        for idx, key in enumerate(panel_keys):
            wid = panel_widget_id(idx)
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{wid}", AgentList
                )
            except NoMatches:
                return False
            ordered_widgets.append(widget)

            if idx == 0:
                widget.remove_class("agent-panel-separated")
            else:
                widget.add_class("agent-panel-separated")

            if idx == focused_idx:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")

            panel_collapsed = key in collapsed_keys
            selected_expanded = bool(
                panel_focus is not None
                and not panel_focus.collapsed
                and panel_focus.panel_key == key
            )
            if selected_expanded:
                widget.add_class("-whole-panel-focus")
                widget.clear_highlight()
            else:
                widget.remove_class("-whole-panel-focus")
            if panel_collapsed:
                widget.add_class("-collapsed-panel")
            else:
                widget.remove_class("-collapsed-panel")

            if key not in affected_keys:
                continue

            slot = panel_index.slice_for(key)
            panel_agents = slot.agents
            global_indices = slot.global_indices
            global_to_local = slot.global_to_local
            marked_fold_keys = fold_restore_marked.get(key, ())

            self._set_agent_panel_title(
                widget,
                self._agent_panel_title(
                    key,
                    panel_agents,
                    merge_tribe_panels=merge_tribe_panels,
                    panel_jump_hints=panel_jump_hints,
                    isolation_restore_marked=key in isolation_marked_keys,
                    fold_restore_marked_count=len(marked_fold_keys),
                ),
            )

            local_idx = -1
            if (
                idx == focused_idx
                and not selected_expanded
                and 0 <= global_idx < len(self._agents)
            ):
                local_idx = global_to_local.get(global_idx, -1)

            local_jump_hints: dict[int, str] | None = None
            if jump_hints:
                local_jump_hints = {}
                for local_i, gi in enumerate(global_indices):
                    if gi in jump_hints:
                        local_jump_hints[local_i] = jump_hints[gi]

            local_banner_hints: dict[tuple[str, ...], str] | None = None
            if banner_jump_hints:
                local_banner_hints = {
                    group_key: hint
                    for (
                        kind,
                        panel_idx,
                        group_key,
                    ), hint in banner_jump_hints.items()
                    if kind == "banner" and panel_idx == idx
                }
                if not local_banner_hints:
                    local_banner_hints = None

            local_tribe_labels: list[str | None] | None = None
            if merge_tribe_panels:
                local_tribe_labels = [
                    effective_tribes[gi]
                    if 0 <= gi < len(effective_tribes)
                    and effective_tribes[gi] is not None
                    else None
                    for gi in global_indices
                ]

            if panel_collapsed:
                widget.render_collapsed()
            else:
                widget.update_list(
                    panel_agents,
                    local_idx,
                    fold_counts=fold_counts,
                    marked_agents=marked,
                    unread_agents=unread,
                    fold_restore_marked_keys=marked_fold_keys,
                    jump_hints=local_jump_hints,
                    banner_jump_hints=local_banner_hints,
                    current_attempt_number=(
                        attempt_number if idx == focused_idx else None
                    ),
                    fold_registry=panel_fold_registry(self, key),
                    current_group_key=(
                        current_group_key
                        if idx == focused_idx and not selected_expanded
                        else None
                    ),
                    grouping_mode=grouping_mode,
                    tribe_labels=local_tribe_labels,
                    panel_tribe=key if not merge_tribe_panels else None,
                    parents_with_visible_children=visible_parent_keys,
                    fully_expanded_parents=fully_expanded_parent_keys,
                )

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()
        return True
