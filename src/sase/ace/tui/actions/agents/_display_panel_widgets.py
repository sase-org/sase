"""AgentList mounting and selective panel-widget refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import panel_widget_id
from ._display_panel_state import PanelRefreshStateMixin
from ._fold_scope import panel_fold_registry

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
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        effective_tags: list[PanelKey] = []
        if merge_tag_panels:
            from ...models.agent_panels import effective_tag_per_agent

            effective_tags = effective_tag_per_agent(self._agents)

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
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())

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
            self._set_agent_panel_title(
                widget,
                self._agent_panel_title(
                    key,
                    panel_agents,
                    merge_tag_panels=merge_tag_panels,
                    panel_jump_hints=panel_jump_hints,
                ),
            )
            if idx == 0:
                widget.remove_class("agent-panel-separated")
            else:
                widget.add_class("agent-panel-separated")

            local_idx = -1
            if idx == focused_idx and 0 <= global_idx < len(self._agents):
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

            local_tag_labels: list[str | None] | None = None
            if merge_tag_panels:
                local_tag_labels = [
                    effective_tags[gi]
                    if 0 <= gi < len(effective_tags) and effective_tags[gi] is not None
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
                    jump_hints=local_jump_hints,
                    banner_jump_hints=local_banner_hints,
                    current_attempt_number=(
                        attempt_number if idx == focused_idx else None
                    ),
                    fold_registry=panel_fold_registry(self, key),
                    current_group_key=(
                        current_group_key if idx == focused_idx else None
                    ),
                    grouping_mode=grouping_mode,
                    tag_labels=local_tag_labels,
                    panel_tag=key if not merge_tag_panels else None,
                )

            if idx == focused_idx:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")

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
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        effective_tags: list[PanelKey] = []
        if merge_tag_panels:
            from ...models.agent_panels import effective_tag_per_agent

            effective_tags = effective_tag_per_agent(self._agents)

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

        focused_idx = self._panel_group.focused_idx
        marked = self._marked_agents
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        fold_counts = self._fold_counts
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())

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

            self._set_agent_panel_title(
                widget,
                self._agent_panel_title(
                    key,
                    panel_agents,
                    merge_tag_panels=merge_tag_panels,
                    panel_jump_hints=panel_jump_hints,
                ),
            )

            local_idx = -1
            if idx == focused_idx and 0 <= global_idx < len(self._agents):
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

            local_tag_labels: list[str | None] | None = None
            if merge_tag_panels:
                local_tag_labels = [
                    effective_tags[gi]
                    if 0 <= gi < len(effective_tags) and effective_tags[gi] is not None
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
                    jump_hints=local_jump_hints,
                    banner_jump_hints=local_banner_hints,
                    current_attempt_number=(
                        attempt_number if idx == focused_idx else None
                    ),
                    fold_registry=panel_fold_registry(self, key),
                    current_group_key=(
                        current_group_key if idx == focused_idx else None
                    ),
                    grouping_mode=grouping_mode,
                    tag_labels=local_tag_labels,
                    panel_tag=key if not merge_tag_panels else None,
                )

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()
        return True
