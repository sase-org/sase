"""Keymap actions and pointer input for the Admin Center Statistics pane."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from textual import on
from textual.containers import VerticalScroll
from textual.events import Click, Key
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import split_key_alternatives
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.time import get_timezone
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


class StatisticsPaneActionsMixin(StatisticsPaneLayoutMixin):
    """Drive Statistics pane state from keymap actions and pointer input."""

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

    def action_next_row(self) -> None:
        """Move the selected Footprint row down without reloading data."""
        self._move_footprint_row(1)

    def action_prev_row(self) -> None:
        """Move the selected Footprint row up without reloading data."""
        self._move_footprint_row(-1)

    def _move_footprint_row(self, delta: int) -> None:
        if self._view != "footprint":
            return
        items = self._footprint_items()
        if not items:
            return
        self._footprint_selected_index = (self._footprint_selected_index + delta) % len(
            items
        )
        # The highlight paints inline (tui_perf rule 7); the evidence card
        # follows through the debouncer instead of blocking the keypress.
        self._paint_current_view()
        self._schedule_footprint_card()

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

    def action_keep_feature(self) -> None:
        """Open the reason picker for the selected feature."""
        row = self._footprint_selected_feature()
        if row is None:
            return
        from .statistics_footprint_review_modal import (
            StatisticsFootprintKeepReasonModal,
        )

        feature_id = str(row["id"])

        def on_reason(reason: str | None) -> None:
            if reason is not None:
                self._record_footprint_decision(feature_id, "keep", reason)

        self.app.push_screen(StatisticsFootprintKeepReasonModal(), on_reason)

    def action_later_feature(self) -> None:
        """Snooze the selected feature for the ledger's 30-day default."""
        row = self._footprint_selected_feature()
        if row is not None:
            self._record_footprint_decision(str(row["id"]), "later", None)

    def action_cut_feature(self) -> None:
        """Mark the selected feature for a reviewed cut plan."""
        row = self._footprint_selected_feature()
        if row is not None:
            self._record_footprint_decision(str(row["id"]), "cut", None)

    def action_undo_feature_decision(self) -> None:
        """Clear the selected feature's local review decision."""
        row = self._footprint_selected_feature()
        if row is not None and row.get("decision") is not None:
            self._record_footprint_decision(str(row["id"]), "clear", None)

    def _record_footprint_decision(
        self,
        feature_id: str,
        decision: str,
        reason: str | None,
    ) -> None:
        """Persist a local review decision away from Textual's message pump."""
        if self._review_worker_running():
            return
        from sase.footprint.query import record_decision

        def task() -> dict[str, Any]:
            return record_decision(feature_id, decision, reason)

        self._footprint_decision_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="statistics-footprint-review-decision",
            exit_on_error=False,
        )

    def _on_footprint_decision_worker_state(self, event: Worker.StateChanged) -> None:
        """Refresh the report after a local decision is durably recorded."""
        if event.state == WorkerState.SUCCESS:
            payload = event.worker.result
            decision = payload.get("decision") if isinstance(payload, Mapping) else None
            feature_id = (
                payload.get("feature_id") if isinstance(payload, Mapping) else None
            )
            label = str(feature_id or "Feature")
            if decision in (None, "clear"):
                self.notify(f"Review decision cleared for {label}")
            else:
                self.notify(f"Marked {label} as {decision}")
            self._schedule_load()
        elif event.state == WorkerState.ERROR:
            message = (
                str(event.worker.error) if event.worker.error else "decision failed"
            )
            self.notify(
                f"Could not save Footprint decision: {message}", severity="error"
            )
            self._schedule_load()
        if event.state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            self._footprint_decision_worker = None

    def action_finish_footprint_review(self) -> None:
        """Load all decisions, then ask before launching their review macro."""
        if self._view != "footprint" or self._review_worker_running():
            return

        def task() -> tuple[str, Any]:
            from sase.footprint.query import build_report_request, fetch_report
            from sase.footprint.render import review_markdown
            from .statistics_footprint_review_modal import FootprintReviewCounts

            report = fetch_report(
                build_report_request(
                    lens="decisions",
                    actor="everyone",
                    window_days=None,
                )
            )
            rows = report.get("rows", [])
            counts = {"keep": 0, "later": 0, "cut": 0}
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, Mapping) and row.get("decision") in counts:
                        counts[str(row["decision"])] += 1
            return (
                review_markdown(report),
                FootprintReviewCounts(
                    keep=counts["keep"],
                    later=counts["later"],
                    cut=counts["cut"],
                ),
            )

        self._footprint_finish_review_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="statistics-footprint-review-finish",
            exit_on_error=False,
        )

    def _on_footprint_finish_review_worker_state(
        self,
        event: Worker.StateChanged,
    ) -> None:
        """Open a confirmation modal for a freshly loaded decision set."""
        if event.state == WorkerState.SUCCESS:
            payload = event.worker.result
            if not (
                isinstance(payload, tuple)
                and len(payload) == 2
                and isinstance(payload[0], str)
            ):
                return
            markdown, counts = payload
            if counts.actionable == 0:
                self.notify("Mark a feature keep or cut before finishing the review")
                self._footprint_finish_review_worker = None
                return
            from .statistics_footprint_review_modal import (
                StatisticsFootprintFinishReviewModal,
            )

            def on_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._launch_footprint_review(markdown)

            self.app.push_screen(
                StatisticsFootprintFinishReviewModal(counts),
                on_confirm,
            )
        elif event.state == WorkerState.ERROR:
            message = (
                str(event.worker.error) if event.worker.error else "review load failed"
            )
            self.notify(
                f"Could not prepare Footprint review: {message}", severity="error"
            )
        if event.state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            self._footprint_finish_review_worker = None

    def _launch_footprint_review(self, markdown: str) -> None:
        """Submit the confirmed review through ACE's normal launch guards."""
        app = self.app
        setup = getattr(app, "_setup_home_prompt_context", None)
        finish = getattr(app, "_finish_agent_launch", None)
        if not callable(setup) or not callable(finish):
            self.notify(
                "Agent launch is unavailable from this Statistics pane",
                severity="error",
            )
            return
        prompt = f"+sase\n#footprint_review::\n\n{markdown}"
        try:
            setup(
                display_name="Footprint review",
                history_sort_key="footprint-review",
                prompt_origin="generated",
            )
            finish(prompt, prompt_origin="generated")
        except Exception as exc:  # noqa: BLE001 - keep launch issues in the UI.
            self.notify(f"Could not launch Footprint review: {exc}", severity="error")

    def _footprint_card_window(self) -> tuple[int | None, str]:
        """Derive card window days and today exactly as the view loader does."""
        selected_range = self._range
        duration_seconds = max(1, selected_range.end_ts - selected_range.start_ts)
        window_days = (
            None
            if selected_range.start_ts <= 0
            else max(1, math.ceil(duration_seconds / 86_400))
        )
        end_ts = max(0, selected_range.end_ts - 1)
        today = datetime.fromtimestamp(end_ts, tz=get_timezone()).date().isoformat()
        return window_days, today

    def _schedule_footprint_card(self) -> None:
        """Debounce the evidence card fetch; the highlight already painted."""
        if self._view != "footprint":
            return
        debouncer = self._footprint_card_debouncer
        if debouncer is None:
            self._start_footprint_card_load()
            return
        debouncer.schedule(self._start_footprint_card_load)

    def _start_footprint_card_load(self) -> None:
        """Fetch the evidence card for the current selection in a worker."""
        if self._view != "footprint":
            return
        from .statistics_pane_footprint import fetch_footprint_card

        target = self._footprint_card_target()
        if target is None:
            self._footprint_card = None
            self._footprint_card_for = None
            self._footprint_card_error = ""
            self._footprint_card_loading = False
            return
        self._footprint_card_generation += 1
        generation = self._footprint_card_generation
        actor = self._footprint_actor
        window_days, today = self._footprint_card_window()
        card_worker = self._footprint_card_worker
        if card_worker is not None and card_worker.state in (
            WorkerState.PENDING,
            WorkerState.RUNNING,
        ):
            card_worker.cancel()
        self._footprint_card_loading = True
        self._footprint_card_error = ""

        def task() -> tuple[int, tuple[str, str], dict[str, Any]]:
            card = fetch_footprint_card(
                target, actor=actor, window_days=window_days, today=today
            )
            return (generation, target, card)

        self._footprint_card_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="statistics-footprint-card",
            exit_on_error=False,
        )
        self._paint_current_view()

    def _on_footprint_card_worker_state(self, event: Worker.StateChanged) -> None:
        """Apply a finished card fetch only when it still matches selection."""
        worker = event.worker
        if event.state == WorkerState.SUCCESS:
            payload = worker.result
            if not (isinstance(payload, tuple) and len(payload) == 3):
                return
            generation, target, card = payload
            if generation != self._footprint_card_generation:
                return
            if not isinstance(card, dict):
                return
            if target != self._footprint_card_target():
                return
            self._footprint_card = card
            self._footprint_card_for = target
            self._footprint_card_error = ""
            self._footprint_card_loading = False
            if self._view == "footprint":
                self._paint_current_view()
        elif event.state == WorkerState.ERROR:
            message = str(worker.error) if worker.error else "card load failed"
            self._footprint_card_loading = False
            if self._footprint_card is None:
                self._footprint_card_error = message
            if self._view == "footprint":
                self._paint_current_view()

    def _apply_pending_footprint_highlight(self) -> None:
        """Highlight the finder-chosen feature once its drill rows land."""
        pending = self._footprint_pending_highlight
        if pending is None or self._view != "footprint":
            return
        self._footprint_pending_highlight = None
        items = self._footprint_items()
        for index, item in enumerate(items):
            if item.get("id") == pending:
                self._footprint_selected_index = index
                return
        self._footprint_selected_index = 0

    def action_open_row(self) -> None:
        """Drill from the map into the selected area's feature rows."""
        if self._view != "footprint" or self._footprint_lens != "map":
            return
        if self._footprint_area is not None:
            return
        items = self._footprint_items()
        if not items:
            return
        selected = items[self._footprint_selected_index]
        area = selected.get("area")
        if not isinstance(area, str) or not area:
            return
        self._footprint_area = area
        self._footprint_selected_index = 0
        self._selection_changed(reload=True)

    def action_drill_up(self) -> None:
        """Return from area details to the complete Footprint map."""
        if self._view != "footprint" or self._footprint_area is None:
            return
        self._footprint_area = None
        self._footprint_selected_index = 0
        self._selection_changed(reload=True)

    def action_find_feature(self) -> None:
        """Open the filterable feature finder over the whole catalog."""
        if self._view != "footprint":
            return
        from .statistics_footprint_finder_modal import (
            FootprintFeatureChoice,
            StatisticsFootprintFinderModal,
            catalog_features,
        )

        try:
            features = catalog_features()
        except Exception as exc:
            self.notify(f"Feature catalog unavailable: {exc}", severity="error")
            return

        def on_picked(choice: FootprintFeatureChoice | None) -> None:
            if choice is None or not choice.feature_id:
                return
            # Switch to the All-features drill of the feature's area with
            # the chosen feature highlighted once its rows land.
            self._footprint_lens = "map"
            self._footprint_area = choice.area
            self._footprint_selected_index = 0
            self._footprint_pending_highlight = choice.feature_id
            self._selection_changed(reload=True)
            self.focus()

        self.app.push_screen(
            StatisticsFootprintFinderModal(
                features,
                current_feature_id=self._footprint_current_feature_id(),
            ),
            on_picked,
        )

    def action_copy_feature_id(self) -> None:
        """Copy the selected feature ID (or area name) to the clipboard."""
        if self._view != "footprint":
            return
        target = self._footprint_card_target()
        if target is None:
            return
        _kind, name = target
        try:
            from sase.ace.tui.actions.clipboard import schedule_copy_delivery

            schedule_copy_delivery(
                self.app,
                name,
                copied_label="Feature ID",
                task_name="footprint-pane-copy-feature-id",
            )
        except Exception:
            try:
                self.app.copy_to_clipboard(name)  # type: ignore[attr-defined]
            except Exception:
                self.notify(f"copy {name}", severity="information")

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


__all__ = ["StatisticsPaneActionsMixin"]
