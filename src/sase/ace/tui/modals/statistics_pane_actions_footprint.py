"""Footprint row, card, and review actions for the Statistics pane."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from textual.worker import Worker, WorkerState

from sase.core.time import get_timezone
from .statistics_pane_actions_views import StatisticsPaneActionsViewsMixin


class StatisticsPaneActionsFootprintMixin(StatisticsPaneActionsViewsMixin):
    """Drive Footprint navigation, evidence cards, and review decisions."""

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


__all__ = ["StatisticsPaneActionsFootprintMixin"]
