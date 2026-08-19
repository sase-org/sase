"""Keymap actions and pointer input for the Admin Center Statistics pane."""

from __future__ import annotations

from typing import cast

from textual import on
from textual.containers import VerticalScroll
from textual.events import Click, Key
from textual.widgets import Input, Static

from sase.ace.tui.keymaps import split_key_alternatives
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.stats.ranges import PRESET_ORDER, StatsRange, parse_custom_range

from .statistics_pane_data import (
    PERF_GROUP_ORDER,
    PROJECTS_GROUP_ORDER,
    XPROMPTS_GROUP_ORDER,
    VIEW_LABELS,
    VIEW_ORDER,
    StatisticsView,
    statistics_view_supports_grouping,
)
from .statistics_pane_layout import OVERVIEW_TILE_TARGETS, StatisticsPaneLayoutMixin


class StatisticsPaneActionsMixin(StatisticsPaneLayoutMixin):
    """Drive Statistics pane state from keymap actions and pointer input."""

    _custom_range_value: str | None
    _project_filter_options: tuple[str, ...]
    _project_filter_seeded: bool
    _xprompt_focus_options: tuple[str, ...]

    def _resolve_current_range(self) -> StatsRange:
        """Resolve the selected range; :class:`StatisticsPane` implements it."""
        raise NotImplementedError

    def _schedule_load(self) -> None:
        """Coalesce a reload; :class:`StatisticsPane` implements it."""
        raise NotImplementedError

    def on_key(self, event: Key) -> None:
        """Resolve one armed numbered-view selection before modal bindings."""
        try:
            if self.query_one("#statistics-custom-range", Input).has_focus:
                return
        except Exception:
            pass
        if not self._pending_view_select:
            return

        if event.key in split_key_alternatives(self._keymaps.select_view):
            event.prevent_default()
            event.stop()
            return

        if event.key in split_key_alternatives(self._keymaps.jump_to_entry):
            event.prevent_default()
            event.stop()
            self._pending_view_select = False
            self._update_hints()
            return

        character = getattr(event, "character", None)
        selected_digit = (
            character
            if isinstance(character, str) and character.isdecimal()
            else event.key
        )
        if isinstance(selected_digit, str) and selected_digit.isdecimal():
            event.prevent_default()
            event.stop()
            self._pending_view_select = False
            view_index = int(selected_digit) - 1
            if 0 <= view_index < len(VIEW_ORDER):
                self._set_view(VIEW_ORDER[view_index])
            self._update_hints()
            return

        self._pending_view_select = False
        self._update_hints()

    def action_prev_view(self) -> None:
        """Select the previous Statistics view."""
        self._cycle_view(-1)

    def action_next_view(self) -> None:
        """Select the next Statistics view."""
        self._cycle_view(1)

    def action_select_view(self) -> None:
        """Arm one-shot numbered Statistics view selection."""
        self._pending_view_select = True
        self._update_hints()

    def action_jump_to_entry(self) -> None:
        """Arm numbered-view selection via the Admin Center-wide jump key.

        Statistics has no row cursor, so unlike other Admin Center tabs it
        does not use ``PaneEntryJumpMixin`` — pressing ' just arms the same
        numbered-view selection ``select_view`` already arms. Do not "fix"
        this pane onto the mixin without re-reading the epic design notes.
        """
        self.action_select_view()

    def action_cycle_range(self) -> None:
        """Cycle through Today, 24h, 7d, 30d, 90d, and All."""
        self._cycle_range(1)

    def action_cycle_range_reverse(self) -> None:
        """Cycle backward through All, 90d, 30d, 7d, 24h, and Today."""
        self._cycle_range(-1)

    def _cycle_range(self, delta: int) -> None:
        """Select the next preset in ``delta`` direction and schedule a reload."""
        if self._preset_key is None:
            next_key = PRESET_ORDER[0] if delta > 0 else PRESET_ORDER[-1]
        else:
            index = PRESET_ORDER.index(self._preset_key)
            next_key = PRESET_ORDER[(index + delta) % len(PRESET_ORDER)]
        self._preset_key = next_key
        self._custom_range_value = None
        self._range = self._resolve_current_range()
        self._selection_changed(reload=True)

    def action_custom_range(self) -> None:
        """Open the inline custom-range editor."""
        custom_input = self.query_one("#statistics-custom-range", Input)
        custom_input.display = True
        custom_input.value = self._custom_range_value or ""
        custom_input.cursor_position = len(custom_input.value)
        custom_input.focus()

    def action_cycle_group(self) -> None:
        """Cycle the active view's grouping strategy when it supports one."""
        if not statistics_view_supports_grouping(self._view):
            return
        if self._view == "projects":
            index = PROJECTS_GROUP_ORDER.index(self._projects_group_by)
            self._projects_group_by = PROJECTS_GROUP_ORDER[
                (index + 1) % len(PROJECTS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)
        elif self._view == "xprompts":
            index = XPROMPTS_GROUP_ORDER.index(self._xprompts_group_by)
            self._xprompts_group_by = XPROMPTS_GROUP_ORDER[
                (index + 1) % len(XPROMPTS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)
        elif self._view == "perf":
            index = PERF_GROUP_ORDER.index(self._perf_group_by)
            self._perf_group_by = PERF_GROUP_ORDER[(index + 1) % len(PERF_GROUP_ORDER)]
            self._selection_changed(reload=True)

    def action_cycle_project_filter(self) -> None:
        """Cycle forward through All and cached ranked projects."""
        self._cycle_project_filter(1)

    def action_cycle_project_filter_reverse(self) -> None:
        """Cycle backward through All and cached ranked projects."""
        self._cycle_project_filter(-1)

    def action_focus_xprompt(self) -> None:
        """Open the cached xprompt picker while viewing loaded XPrompts data."""
        if self._view != "xprompts" or self._last_result is None:
            return
        from .statistics_xprompt_picker_modal import (
            StatisticsXPromptPickerModal,
            XPromptFocusChoice,
        )

        rows = self._last_result.views.xprompts.rows
        if self._xprompt_focus_options:
            by_name = {row.name: row for row in rows}
            rows = tuple(
                by_name[name] for name in self._xprompt_focus_options if name in by_name
            )

        def on_picked(choice: XPromptFocusChoice | None) -> None:
            if choice is None:
                return
            self._xprompt_focus = choice.name
            self._selection_changed(reload=True)
            self.focus()

        self.app.push_screen(
            StatisticsXPromptPickerModal(
                rows,
                current_focus=self._xprompt_focus,
            ),
            on_picked,
        )

    def action_clear_xprompt_focus(self) -> None:
        """Return to all xprompts when a focus is active."""
        if self._xprompt_focus is None:
            return
        self._xprompt_focus = None
        self._selection_changed(reload=True)

    def _cycle_project_filter(self, delta: int) -> None:
        """Cycle projects in ``delta`` direction or escape an empty filter."""
        # A manual cycle is an explicit choice: settle the seed guard so a
        # current-project resolve that lands afterward cannot override it.
        self._project_filter_seeded = True
        if (
            self._project_filter is not None
            and self._last_result is not None
            and self._last_result.project_filter == self._project_filter
            and self._last_result.views.empty
        ):
            self._project_filter = None
            self._selection_changed(reload=True)
            return
        options = self._project_filter_options
        if not options and self._last_result is not None:
            options = tuple(
                row.project_key for row in self._last_result.views.projects.projects
            )
        if not options:
            return
        cycle: tuple[str | None, ...] = (None, *options)
        try:
            index = cycle.index(self._project_filter)
        except ValueError:
            index = 0
        self._project_filter = cycle[(index + delta) % len(cycle)]
        self._selection_changed(reload=True)

    def action_scroll_down(self) -> None:
        """Move the Statistics body down by half of its visible height."""
        self._scroll_body(1)

    def action_scroll_up(self) -> None:
        """Move the Statistics body up by half of its visible height."""
        self._scroll_body(-1)

    def _scroll_body(self, direction: int) -> None:
        """Scroll the mounted body immediately without loading or repainting."""
        try:
            if self.query_one("#statistics-custom-range", Input).has_focus:
                return
            scroll = self.query_one("#statistics-body-scroll", VerticalScroll)
        except Exception:
            return
        distance = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=direction * distance, animate=False)

    def action_refresh(self) -> None:
        """Coalesce a manual refresh through the worker-backed load path."""
        self._schedule_load()

    def action_help(self) -> None:
        """Open contextual help built only from already-loaded pane state."""
        from .statistics_help_modal import StatisticsHelpModal

        result = self._last_result
        project_label = "All projects"
        if self._project_filter is not None:
            project_label = self._project_filter
            if result is not None:
                project_label = result.project_display_snapshot.label_for(
                    self._project_filter
                )
        self.app.push_screen(
            StatisticsHelpModal(
                current_view=self._view,
                selected_range=self._range,
                projects_group_by=self._projects_group_by,
                xprompts_group_by=self._xprompts_group_by,
                perf_group_by=self._perf_group_by,
                project_label=project_label,
                xprompt_focus_label=(
                    "All xprompts"
                    if self._xprompt_focus is None
                    else f"#{self._xprompt_focus}"
                ),
                generated_at=result.generated_at if result is not None else None,
                keymaps=self._keymaps,
            )
        )

    @on(PanelTabStrip.TabClicked)
    def _on_view_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id in VIEW_ORDER:
            self._set_view(cast(StatisticsView, event.tab_id))

    def on_click(self, event: Click) -> None:
        """Navigate from Overview tiles only; Perf tiles are non-interactive."""
        if self._view != "overview":
            return
        widget_id = getattr(event.widget, "id", None)
        if not isinstance(widget_id, str) or not widget_id.startswith(
            "statistics-tile-"
        ):
            return
        try:
            index = int(widget_id.removeprefix("statistics-tile-"))
        except ValueError:
            return
        if 0 <= index < len(OVERVIEW_TILE_TARGETS):
            event.stop()
            self._set_view(OVERVIEW_TILE_TARGETS[index][1])

    @on(Input.Submitted, "#statistics-custom-range")
    def _on_custom_range_submitted(self, event: Input.Submitted) -> None:
        try:
            selected_range = parse_custom_range(event.value)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            event.input.select_all()
            return
        self._preset_key = None
        self._custom_range_value = event.value.strip()
        self._range = selected_range
        self._close_custom_range()
        self._selection_changed(reload=True)

    def _cycle_view(self, delta: int) -> None:
        index = VIEW_ORDER.index(self._view)
        self._set_view(VIEW_ORDER[(index + delta) % len(VIEW_ORDER)])

    def _configure_overview_tile_widgets(self) -> None:
        """Restore Overview click-through tooltips after painting those tiles."""
        for index, (_caption, target_view) in enumerate(OVERVIEW_TILE_TARGETS):
            try:
                tile = self.query_one(f"#statistics-tile-{index}", Static)
            except Exception:
                continue
            tile.tooltip = f"Open {VIEW_LABELS[target_view]}"

    def _set_view(self, view: StatisticsView) -> None:
        if view == self._view:
            return
        self._view = view
        try:
            self.query_one("#statistics-views", PanelTabStrip).set_active_tab(view)
        except Exception:
            pass
        needs_perf = view == "perf" and (
            self._last_result is None or self._last_result.perf is None
        )
        self._selection_changed(reload=needs_perf)

    def _selection_changed(self, *, reload: bool) -> None:
        self._last_error = ""
        self._update_heading()
        self._update_hints()
        if reload:
            self._schedule_load()
        else:
            self._paint_current_view()


__all__ = ["StatisticsPaneActionsMixin"]
