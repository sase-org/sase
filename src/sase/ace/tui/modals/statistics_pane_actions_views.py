"""View, range, and group actions for the Admin Center Statistics pane."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from textual import on
from textual.events import Click, Key
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import split_key_alternatives
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.stats.loader import StatisticsViewData
from sase.stats.ranges import PRESET_ORDER, PresetKey, StatsRange, parse_stats_range
from sase.stats.registry import (
    FOOTPRINT_ACTOR_ORDER,
    FOOTPRINT_LENS_ORDER,
    MACROS_GROUP_ORDER,
    PERF_GROUP_ORDER,
    VIEW_LABELS,
    VIEW_ORDER,
    StatisticsView,
    statistics_view_supports_grouping,
    validated_statistics_view,
)
from .statistics_pane_layout import OVERVIEW_TILE_TARGETS, StatisticsPaneLayoutMixin


class StatisticsPaneActionsViewsMixin(StatisticsPaneLayoutMixin):
    """Drive view, range, and grouping state for the Statistics pane."""

    _custom_range_value: str | None
    _project_filter_options: tuple[str, ...]
    _project_filter_seeded: bool
    _macro_focus_options: tuple[str, ...]
    _footprint_lens: str
    _footprint_actor: str
    _footprint_area: str | None
    _footprint_selected_index: int
    _footprint_card: dict[str, Any] | None
    _footprint_card_for: tuple[str, str] | None
    _footprint_card_error: str
    _footprint_card_loading: bool
    _footprint_card_generation: int
    _footprint_card_worker: Worker[Any] | None
    _footprint_card_debouncer: DetailPanelDebouncer | None
    _footprint_pending_highlight: str | None
    _footprint_decision_worker: Worker[Any] | None
    _footprint_finish_review_worker: Worker[Any] | None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        review_actions = {
            "keep_feature",
            "later_feature",
            "cut_feature",
            "undo_feature_decision",
        }
        if action in review_actions:
            if self._view != "footprint" or self._review_worker_running():
                return False
            row = self._footprint_selected_feature()
            if row is None:
                return False
            if action == "undo_feature_decision":
                return row.get("decision") is not None
            return True
        if action == "finish_footprint_review":
            return self._view == "footprint" and not self._review_worker_running()
        if action in {"find_feature", "copy_feature_id"}:
            if self._view != "footprint":
                return False
            if action == "find_feature":
                return True
            return bool(self._footprint_items())
        if action in {"cycle_actor", "next_row", "prev_row", "open_row", "drill_up"}:
            if self._view != "footprint":
                return False
            if action == "cycle_actor":
                return True
            if action == "open_row":
                return (
                    self._footprint_lens == "map"
                    and self._footprint_area is None
                    and bool(self._footprint_items())
                )
            if action == "drill_up":
                return self._footprint_area is not None
            return bool(self._footprint_items())
        if self._view == "footprint" and action in {
            "cycle_project_filter",
            "cycle_project_filter_reverse",
            "focus_macro",
            "clear_macro_focus",
        }:
            return False
        return super().check_action(action, parameters)

    def _review_worker_running(self) -> bool:
        """Return whether a decision write or finish-review query is pending."""
        return any(
            worker is not None
            and worker.state in (WorkerState.PENDING, WorkerState.RUNNING)
            for worker in (
                self._footprint_decision_worker,
                self._footprint_finish_review_worker,
            )
        )

    def _resolve_current_range(self) -> StatsRange:
        """Resolve the selected range; :class:`StatisticsPane` implements it."""
        raise NotImplementedError

    def _schedule_load(self) -> None:
        """Coalesce a reload; :class:`StatisticsPane` implements it."""
        raise NotImplementedError

    def _footprint_items(
        self,
        report: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the rows shown by the selected Footprint lens."""
        if report is None:
            result = getattr(self, "_last_result", None)
            report = (
                result.footprint if isinstance(result, StatisticsViewData) else None
            )
        if not isinstance(report, Mapping):
            return ()
        if self._footprint_lens == "map" and self._footprint_area is None:
            key = "areas"
        elif self._footprint_lens == "coverage" and self._footprint_area is None:
            key = "coverage"
        else:
            key = "rows"
        values = report.get(key, [])
        if not isinstance(values, list):
            return ()
        return tuple(dict(value) for value in values if isinstance(value, Mapping))

    def _footprint_card_target(self) -> tuple[str, str] | None:
        """Return the ``(kind, name)`` the evidence card should show, if any."""
        if self._view != "footprint":
            return None
        if self._footprint_lens == "coverage" and self._footprint_area is None:
            return None
        items = self._footprint_items()
        if not items:
            return None
        selected = items[min(max(0, self._footprint_selected_index), len(items) - 1)]
        if self._footprint_lens == "map" and self._footprint_area is None:
            area = selected.get("area")
            if isinstance(area, str) and area:
                return ("area", area)
            return None
        feature_id = selected.get("id")
        if isinstance(feature_id, str) and feature_id:
            return ("feature", feature_id)
        return None

    def _footprint_current_feature_id(self) -> str | None:
        """Return the selected feature ID for the finder and copy actions."""
        card_for = getattr(self, "_footprint_card_for", None)
        if isinstance(card_for, tuple) and card_for[0] == "feature":
            return card_for[1]
        items = self._footprint_items()
        if not items:
            return None
        selected = items[min(max(0, self._footprint_selected_index), len(items) - 1)]
        feature_id = selected.get("id")
        return feature_id if isinstance(feature_id, str) and feature_id else None

    def _footprint_selected_feature(self) -> dict[str, Any] | None:
        """Return the selected feature row, excluding area and coverage rows."""
        if self._view != "footprint":
            return None
        items = self._footprint_items()
        if not items:
            return None
        index = min(max(0, self._footprint_selected_index), len(items) - 1)
        selected = items[index]
        feature_id = selected.get("id")
        return selected if isinstance(feature_id, str) and ":" in feature_id else None

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
            order = self._projects_group_cycle_order()
            current = self._effective_projects_group_by()
            try:
                index = order.index(current)
            except ValueError:
                index = -1
            self._projects_group_by = order[(index + 1) % len(order)]
            self._selection_changed(reload=False)
        elif self._view == "macros":
            index = MACROS_GROUP_ORDER.index(self._macros_group_by)
            self._macros_group_by = MACROS_GROUP_ORDER[
                (index + 1) % len(MACROS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)
        elif self._view == "perf":
            index = PERF_GROUP_ORDER.index(self._perf_group_by)
            self._perf_group_by = PERF_GROUP_ORDER[(index + 1) % len(PERF_GROUP_ORDER)]
            self._selection_changed(reload=True)
        elif self._view == "footprint":
            index = FOOTPRINT_LENS_ORDER.index(self._footprint_lens)
            self._footprint_lens = FOOTPRINT_LENS_ORDER[
                (index + 1) % len(FOOTPRINT_LENS_ORDER)
            ]
            self._footprint_selected_index = 0
            self._selection_changed(reload=True)

    def action_cycle_actor(self) -> None:
        """Cycle Footprint actor scope from you through the full census."""
        if self._view != "footprint":
            return
        index = FOOTPRINT_ACTOR_ORDER.index(self._footprint_actor)
        self._footprint_actor = FOOTPRINT_ACTOR_ORDER[
            (index + 1) % len(FOOTPRINT_ACTOR_ORDER)
        ]
        self._footprint_selected_index = 0
        self._selection_changed(reload=True)

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
            selected_range = parse_stats_range(event.value)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            event.input.select_all()
            return
        stripped = event.value.strip()
        if stripped in PRESET_ORDER:
            self._preset_key = cast(PresetKey, stripped)
            self._custom_range_value = None
        else:
            self._preset_key = None
            self._custom_range_value = stripped
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

    def _set_view(self, view: StatisticsView | str) -> None:
        resolved = validated_statistics_view(view)
        if resolved is None or resolved == self._view:
            return
        try:
            app = self.app  # type: ignore[attr-defined]
            record = getattr(app, "_footprint_record_stats_view", None)
            if callable(record):
                record(resolved)
        except Exception:
            pass
        self._view = resolved
        try:
            self.query_one("#statistics-views", PanelTabStrip).set_active_tab(resolved)
        except Exception:
            pass
        needs_reload = self._last_result is None or not self._result_paints_view(
            self._last_result, resolved
        )
        self._selection_changed(reload=needs_reload)

    def _filtered_result_is_empty(self, result: StatisticsViewData) -> bool:
        if result.view == "projects":
            return result.project_stats is None or not result.project_stats.projects
        return result.views is not None and result.views.empty

    def _project_keys_from_result(self, result: StatisticsViewData) -> tuple[str, ...]:
        if result.project_stats is not None:
            return tuple(project.key for project in result.project_stats.projects)
        if result.views is not None:
            return tuple(row.project_key for row in result.views.projects.projects)
        return ()

    def _selection_changed(self, *, reload: bool) -> None:
        self._last_error = ""
        self._update_heading()
        self._update_hints()
        if reload:
            self._schedule_load()
        else:
            self._paint_current_view()


__all__ = ["StatisticsPaneActionsViewsMixin"]
