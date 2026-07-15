"""Panel-widget refresh, sizing, and highlight helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import TabName, panel_widget_id
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._fold_scope import panel_fold_registry
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...widgets import AgentList


class PanelRefreshMixin:
    """Panel collection, widget refresh, dynamic sizing, and focus helpers."""

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]

    def _sync_panel_group(self) -> None:
        """Recompute :attr:`_panel_group` from the current :attr:`_agents`."""
        from ...models.agent_panels import AgentPanelGroup

        prev_focused = self._panel_group.focused_key
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            prev_focused,
            merge_tag_panels=merge_tag_panels,
        )
        collapsed_keys = getattr(self, "_collapsed_panel_keys", None)
        if collapsed_keys is not None:
            collapsed_keys.intersection_update(self._panel_group.panel_keys)

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        focused_key = self._panel_group.focused_key
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        if 0 <= self.current_idx < len(self._agents):
            if (
                keys_per_agent[self.current_idx] != focused_key
                or panel_index.local_idx_for(focused_key, self.current_idx) < 0
            ):
                self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)
        else:
            self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[PanelKey], focused_key: PanelKey
    ) -> None:
        """Set ``current_idx`` to the first agent in the focused panel."""
        global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
        if global_indices:
            self.current_idx = global_indices[0]
            return
        panel_index_fn = getattr(self, "_agent_panel_index", None)
        non_child_indices = (
            set(panel_index_fn().non_child_indices)
            if callable(panel_index_fn)
            else set(range(len(self._agents)))
        )
        for i, k in enumerate(keys_per_agent):
            if k == focused_key and i in non_child_indices:
                self.current_idx = i
                return
        self.current_idx = 0

    def _refresh_panel_widgets(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[tuple[Literal["banner"], int, tuple[str, ...]], str]
        | None = None,
    ) -> None:
        """Mount/unmount AgentList widgets to match :attr:`_panel_group`."""
        with tui_trace(
            "agents.refresh_panel_widgets",
            agents=len(self._agents),
            panels=len(self._panel_group.panel_keys),
        ):
            self._refresh_panel_widgets_impl(
                jump_hints=jump_hints, banner_jump_hints=banner_jump_hints
            )

    def _refresh_panel_widgets_impl(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[tuple[Literal["banner"], int, tuple[str, ...]], str]
        | None = None,
    ) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return

        panel_keys = self._panel_group.panel_keys
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
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
                widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
            except NoMatches:
                continue
            ordered_widgets.append(widget)

            slot = panel_index.slice_for(key)
            panel_agents = slot.agents
            global_indices = slot.global_indices
            global_to_local = slot.global_to_local

            counts = agent_panel_counts(panel_agents, unread)
            panel_collapsed = key in collapsed_keys
            widget.border_title = agent_panel_border_title(
                key,
                len(panel_agents),
                merge_tag_panels=merge_tag_panels,
                counts=counts,
                collapsed=panel_collapsed,
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
                    for (kind, panel_idx, group_key), hint in banner_jump_hints.items()
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
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return False

        panel_keys = self._panel_group.panel_keys
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
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
                widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
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

            counts = agent_panel_counts(panel_agents, unread)
            widget.border_title = agent_panel_border_title(
                key,
                len(panel_agents),
                merge_tag_panels=merge_tag_panels,
                counts=counts,
                collapsed=panel_collapsed,
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
                    for (kind, panel_idx, group_key), hint in banner_jump_hints.items()
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
                )

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()
        return True

    def _apply_panel_heights(self, container: object, widgets: list[AgentList]) -> None:
        """Size each tag panel based on its content."""
        if not widgets:
            return

        size = getattr(container, "size", None)
        container_height = getattr(size, "height", 0) if size is not None else 0
        if not container_height:
            return

        border_rows = 2
        option_counts = [max(0, int(getattr(w, "option_count", 0))) for w in widgets]
        panel_keys = getattr(self._panel_group, "panel_keys", [])
        if len(panel_keys) == len(widgets):
            collapsed_keys: set[PanelKey] = getattr(
                self, "_collapsed_panel_keys", set()
            )
            collapsed = [key in collapsed_keys for key in panel_keys]
        else:
            collapsed = [
                bool(getattr(widget, "_panel_collapsed", False)) for widget in widgets
            ]
        natural_heights = [
            border_rows if collapsed[idx] else count + border_rows
            for idx, count in enumerate(option_counts)
        ]
        separator_rows = max(0, len(widgets) - 1)
        total_natural = sum(natural_heights) + separator_rows

        from textual.css.scalar import Scalar, Unit

        def cell_height(rows: float) -> Scalar:
            return Scalar(float(rows), Unit.CELLS, Unit.HEIGHT)

        def fraction_height(idx: int) -> Scalar:
            weight = float(option_counts[idx] + 1)
            return Scalar(weight, Unit.FRACTION, Unit.HEIGHT)

        if total_natural <= container_height:
            filler_idx = next(
                (idx for idx, is_collapsed in enumerate(collapsed) if not is_collapsed),
                None,
            )
            for idx, (widget, natural) in enumerate(
                zip(widgets, natural_heights, strict=True)
            ):
                if idx == filler_idx:
                    widget.styles.height = Scalar(1.0, Unit.FRACTION, Unit.HEIGHT)
                else:
                    widget.styles.height = cell_height(float(natural))
            return

        content_budget = max(0, container_height - separator_rows)
        min_heights = [
            border_rows if collapsed[idx] else border_rows + min(count, 2)
            for idx, count in enumerate(option_counts)
        ]
        if content_budget < sum(min_heights):
            for idx, widget in enumerate(widgets):
                widget.styles.height = (
                    cell_height(float(border_rows))
                    if collapsed[idx]
                    else fraction_height(idx)
                )
            return

        fixed_heights: dict[int, float] = {
            idx: float(border_rows)
            for idx, is_collapsed in enumerate(collapsed)
            if is_collapsed
        }
        first_panel_is_untagged = (
            not getattr(self, "_agent_panels_grouped", False)
            and len(panel_keys) == len(widgets)
            and bool(panel_keys)
            and panel_keys[0] is None
            and not collapsed[0]
        )
        if first_panel_is_untagged:
            half_budget = content_budget / 2.0
            if natural_heights[0] <= half_budget:
                fixed_heights[0] = float(natural_heights[0])
            else:
                fixed_heights[0] = float(max(1, content_budget // 2))

        fixed_total = sum(fixed_heights.values())
        candidates = [idx for idx in range(len(widgets)) if idx not in fixed_heights]
        for idx in sorted(candidates, key=lambda i: (natural_heights[i], i)):
            remaining_min = sum(
                min_heights[other]
                for other in range(len(widgets))
                if other not in fixed_heights and other != idx
            )
            if fixed_total + natural_heights[idx] + remaining_min <= content_budget:
                fixed_heights[idx] = float(natural_heights[idx])
                fixed_total += natural_heights[idx]

        for idx, widget in enumerate(widgets):
            if idx in fixed_heights:
                widget.styles.height = cell_height(fixed_heights[idx])
            else:
                widget.styles.height = fraction_height(idx)

    def _reapply_panel_heights(self) -> None:
        """Re-run the panel-height computation without rebuilding options."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        try:
            widgets = list(
                container.query(AgentList).results(AgentList)  # type: ignore[attr-defined]
            )
        except (AttributeError, NoMatches):
            widgets = [
                w
                for w in getattr(container, "children", [])
                if isinstance(w, AgentList)
            ]
        self._apply_panel_heights(container, widgets)

    def _refresh_panel_highlights(self) -> None:
        """Update the highlight on the focused panel without rebuilding options."""
        with tui_trace("agents.refresh_panel_highlights", agents=len(self._agents)):
            self._refresh_panel_highlights_impl()

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        """Refresh only the widgets affected by a focused-panel switch."""
        with tui_trace(
            "agents.refresh_focused_panel",
            agents=len(self._agents),
            old_focused_idx=old_focused_idx,
            focused_idx=self._panel_group.focused_idx,
        ):
            self._refresh_focused_agent_panel_impl(old_focused_idx=old_focused_idx)

    def _refresh_focused_agent_panel_impl(self, *, old_focused_idx: int | None) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        focused_idx = self._panel_group.focused_idx
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        focused_key = self._panel_group.focused_key
        target_indices = {focused_idx}
        if old_focused_idx is not None:
            target_indices.add(old_focused_idx)

        focused_widget: AgentList | None = None
        for idx in target_indices:
            if idx < 0 or idx >= len(self._panel_group.panel_keys):
                continue
            wid = panel_widget_id(idx)
            try:
                widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
            except NoMatches:
                continue
            if idx == focused_idx:
                local_idx = -1
                if 0 <= self.current_idx < len(self._agents):
                    local_idx = panel_index.local_idx_for(focused_key, self.current_idx)
                if focused_key not in getattr(self, "_collapsed_panel_keys", set()):
                    widget.update_highlight(
                        local_idx,
                        self.current_attempt_number,
                        group_key=self._current_group_key,
                    )
                widget.add_class("-focused-panel")
                focused_widget = widget
            else:
                widget.remove_class("-focused-panel")
                widget.clear_highlight()

        hint_bar_active = getattr(self, "_hint_input_bar_active", None)
        if focused_widget is not None and not (
            callable(hint_bar_active) and hint_bar_active()
        ):
            try:
                focused_widget.focus()
            except Exception:
                pass

    def _refresh_panel_highlights_impl(self) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        focused_key = self._panel_group.focused_key
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        wid = panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        local_idx = -1
        if 0 <= self.current_idx < len(self._agents):
            local_idx = panel_index.local_idx_for(focused_key, self.current_idx)
        widget.update_highlight(
            local_idx,
            self.current_attempt_number,
            group_key=self._current_group_key,
        )

        try:
            for w in self.query("#agent-list-container AgentList").results(AgentList):  # type: ignore[attr-defined]
                if w.id == wid:
                    w.add_class("-focused-panel")
                else:
                    w.remove_class("-focused-panel")
                    w.clear_highlight()
        except NoMatches:
            pass

    def _focus_focused_panel_widget(self) -> None:
        """Set Textual focus on the focused-panel AgentList."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        hint_bar_active = getattr(self, "_hint_input_bar_active", None)
        if callable(hint_bar_active) and hint_bar_active():
            return

        wid = panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        try:
            widget.focus()
        except Exception:
            # Focus may not be available before mount completes; harmless.
            pass
