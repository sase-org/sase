"""Panel-widget refresh, sizing, and highlight helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import TabName, panel_widget_id
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts

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

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        focused_key = self._panel_group.focused_key
        if 0 <= self.current_idx < len(self._agents):
            if keys_per_agent[self.current_idx] != focused_key:
                self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)
        else:
            self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[PanelKey], focused_key: PanelKey
    ) -> None:
        """Set ``current_idx`` to the first agent in the focused panel."""
        for i, k in enumerate(keys_per_agent):
            if k == focused_key:
                self.current_idx = i
                return
        if self._agents:
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
        fold_registry = self._group_fold_registry
        marked = self._marked_agents
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        fold_counts = self._fold_counts
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)

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

            widget.border_title = agent_panel_border_title(
                key,
                len(panel_agents),
                merge_tag_panels=merge_tag_panels,
                counts=agent_panel_counts(panel_agents, unread),
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

            widget.update_list(
                panel_agents,
                local_idx,
                fold_counts=fold_counts,
                marked_agents=marked,
                unread_agents=unread,
                jump_hints=local_jump_hints,
                banner_jump_hints=local_banner_hints,
                current_attempt_number=attempt_number if idx == focused_idx else None,
                fold_registry=fold_registry,
                current_group_key=current_group_key if idx == focused_idx else None,
                grouping_mode=grouping_mode,
                tag_labels=local_tag_labels,
            )

            if idx == focused_idx:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()

    def _apply_panel_heights(self, container: object, widgets: list[AgentList]) -> None:
        """Size each tag panel based on its content."""
        if not widgets:
            return

        size = getattr(container, "size", None)
        container_height = getattr(size, "height", 0) if size is not None else 0
        if not container_height:
            return

        border_rows = 2
        natural_heights = [getattr(w, "option_count", 0) + border_rows for w in widgets]
        separator_rows = max(0, len(widgets) - 1)
        total_natural = sum(natural_heights) + separator_rows

        from textual.css.scalar import Scalar, Unit

        if total_natural <= container_height:
            for idx, (widget, natural) in enumerate(
                zip(widgets, natural_heights, strict=True)
            ):
                if idx == 0:
                    widget.styles.height = Scalar(1.0, Unit.FRACTION, Unit.HEIGHT)
                else:
                    widget.styles.height = Scalar(
                        float(natural), Unit.CELLS, Unit.HEIGHT
                    )
        else:
            for widget in widgets:
                weight = float(getattr(widget, "option_count", 0) + 1)
                widget.styles.height = Scalar(weight, Unit.FRACTION, Unit.HEIGHT)

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

        if focused_widget is not None:
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
