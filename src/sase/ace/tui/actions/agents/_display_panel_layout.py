"""Panel sizing, selection highlighting, and Textual focus helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...util.trace import tui_trace
from ._display_helpers import panel_widget_id
from ._display_panel_state import PanelRefreshStateMixin

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList


class PanelLayoutMixin(PanelRefreshStateMixin):
    """Dynamic panel sizing, highlight, and focus helpers."""

    def _apply_panel_heights(self, container: object, widgets: list[AgentList]) -> None:
        """Size each tribe panel based on its content."""
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
            container = self.query_one(  # type: ignore[attr-defined]
                "#agent-list-container"
            )
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
        panel_index = self._agent_panel_index()
        focused_key = self._panel_group.focused_key
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        selected_expanded = bool(panel_focus is not None and not panel_focus.collapsed)
        target_indices = {focused_idx}
        if old_focused_idx is not None:
            target_indices.add(old_focused_idx)

        focused_widget: AgentList | None = None
        for idx in target_indices:
            if idx < 0 or idx >= len(self._panel_group.panel_keys):
                continue
            wid = panel_widget_id(idx)
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{wid}", AgentList
                )
            except NoMatches:
                continue
            key = self._panel_group.panel_keys[idx]
            panel_agents = panel_index.slice_for(key).agents
            self._set_agent_panel_title(
                widget,
                self._agent_panel_title(
                    key,
                    panel_agents,
                    merge_tribe_panels=getattr(self, "_agent_panels_grouped", False),
                ),
            )
            if idx == focused_idx:
                local_idx = -1
                if 0 <= self.current_idx < len(self._agents):
                    local_idx = panel_index.local_idx_for(focused_key, self.current_idx)
                if selected_expanded:
                    widget.clear_highlight()
                elif focused_key not in getattr(self, "_collapsed_panel_keys", set()):
                    widget.update_highlight(
                        local_idx,
                        self.current_attempt_number,
                        group_key=self._current_group_key,
                    )
                widget.add_class("-focused-panel")
                if selected_expanded:
                    widget.add_class("-whole-panel-focus")
                else:
                    widget.remove_class("-whole-panel-focus")
                focused_widget = widget
            else:
                widget.remove_class("-focused-panel")
                widget.remove_class("-whole-panel-focus")
                widget.clear_highlight()

        hint_bar_active = getattr(self, "_hint_input_bar_active", None)
        if (
            focused_widget is not None
            and panel_focus is None
            and not (callable(hint_bar_active) and hint_bar_active())
        ):
            try:
                focused_widget.focus()
            except Exception:
                pass

    def _refresh_panel_highlights_impl(self) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        focused_key = self._panel_group.focused_key
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        selected_expanded = bool(panel_focus is not None and not panel_focus.collapsed)
        panel_index = self._agent_panel_index()
        wid = panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        local_idx = -1
        if 0 <= self.current_idx < len(self._agents):
            local_idx = panel_index.local_idx_for(focused_key, self.current_idx)
        if selected_expanded:
            widget.clear_highlight()
            widget.add_class("-whole-panel-focus")
        else:
            widget.remove_class("-whole-panel-focus")
            widget.update_highlight(
                local_idx,
                self.current_attempt_number,
                group_key=self._current_group_key,
            )

        # The common single-panel case has no stale sibling highlight to
        # clear. Avoid a descendant query on every j/k tick; the panel class
        # is established during the full render and this idempotent add also
        # covers callers that invoke the helper directly.
        if len(self._panel_group.panel_keys) == 1:
            widget.add_class("-focused-panel")
            return

        try:
            for w in self.query(  # type: ignore[attr-defined]
                "#agent-list-container AgentList"
            ).results(AgentList):
                if w.id == wid:
                    w.add_class("-focused-panel")
                    if selected_expanded:
                        w.add_class("-whole-panel-focus")
                    else:
                        w.remove_class("-whole-panel-focus")
                else:
                    w.remove_class("-focused-panel")
                    w.remove_class("-whole-panel-focus")
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
