"""Project, macro, scroll, and help actions for the Statistics pane."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Input

from .statistics_pane_actions_footprint import StatisticsPaneActionsFootprintMixin


class StatisticsPaneActionsFiltersMixin(StatisticsPaneActionsFootprintMixin):
    """Drive project and macro filters plus scroll, refresh, and help."""

    def action_cycle_project_filter(self) -> None:
        """Cycle forward through All and cached ranked projects."""
        self._cycle_project_filter(1)

    def action_cycle_project_filter_reverse(self) -> None:
        """Cycle backward through All and cached ranked projects."""
        self._cycle_project_filter(-1)

    def action_focus_macro(self) -> None:
        """Open the cached macro picker while viewing loaded Macros data."""
        if (
            self._view != "macros"
            or self._last_result is None
            or self._last_result.views is None
        ):
            return
        from .statistics_macro_picker_modal import (
            StatisticsMacroPickerModal,
            MacroFocusChoice,
        )

        rows = self._last_result.views.macros.rows
        if self._macro_focus_options:
            by_name = {row.name: row for row in rows}
            rows = tuple(
                by_name[name] for name in self._macro_focus_options if name in by_name
            )

        def on_picked(choice: MacroFocusChoice | None) -> None:
            if choice is None:
                return
            self._macro_focus = choice.name
            self._selection_changed(reload=True)
            self.focus()

        self.app.push_screen(
            StatisticsMacroPickerModal(
                rows,
                current_focus=self._macro_focus,
            ),
            on_picked,
        )

    def action_clear_macro_focus(self) -> None:
        """Return to all macros when a focus is active."""
        if self._macro_focus is None:
            return
        self._macro_focus = None
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
            and self._filtered_result_is_empty(self._last_result)
        ):
            self._project_filter = None
            self._selection_changed(reload=True)
            return
        options = self._project_filter_options
        if not options and self._last_result is not None:
            options = self._project_keys_from_result(self._last_result)
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
                projects_group_by=self._effective_projects_group_by(),
                macros_group_by=self._macros_group_by,
                perf_group_by=self._perf_group_by,
                footprint_lens=self._footprint_lens,
                footprint_actor=self._footprint_actor,
                footprint_area=self._footprint_area,
                project_label=project_label,
                macro_focus_label=(
                    "All macros"
                    if self._macro_focus is None
                    else f"#{self._macro_focus}"
                ),
                generated_at=result.generated_at if result is not None else None,
                keymaps=self._keymaps,
            )
        )


__all__ = ["StatisticsPaneActionsFiltersMixin"]
