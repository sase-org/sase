"""Consume Statistics pane worker results and merge Code facet updates."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from textual.worker import Worker, WorkerState

from sase.current_project import CurrentProject
from sase.stats.loader import StatisticsViewData
from sase.stats.project import ProjectStatsView

from ._statistics_pane_load import StatisticsLoadResult
from .statistics_pane_actions import StatisticsPaneActionsMixin
from .statistics_pane_project_merge import merge_project_code_stats


class StatisticsPaneWorkersMixin(StatisticsPaneActionsMixin):
    """Settle primary and Code workers onto the painted Statistics report."""

    _current_project_seed_worker: Worker[Any] | None
    _current_project_resolved: bool
    _current_project_key: str | None
    _project_filter_seeded: bool
    _project_filter_options_ready: bool
    _unmerged_primary: StatisticsViewData | None
    _primary_fingerprint: str | None
    _code_fingerprint: str | None
    _code_complete: bool
    _code_worker: Worker[Any] | None
    _worker: Worker[Any] | None
    _load_generation: int
    _loaded_once: bool

    def _maybe_seed_project_filter(self) -> None:
        """Adopt the current project once, before the user has cycled away."""
        if self._project_filter_seeded:
            return
        if not self._current_project_resolved or not self._project_filter_options_ready:
            return
        self._project_filter_seeded = True
        if (
            self._current_project_key is None
            or self._project_filter is not None
            or self._current_project_key not in self._project_filter_options
        ):
            return
        self._project_filter = self._current_project_key
        self._selection_changed(reload=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._current_project_seed_worker:
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self._current_project_resolved = True
                result = (
                    event.worker.result if event.state == WorkerState.SUCCESS else None
                )
                self._current_project_key = (
                    result.project_key if isinstance(result, CurrentProject) else None
                )
                self._maybe_seed_project_filter()
            return
        if event.worker is self._code_worker:
            self._on_code_worker_state(event)
            return
        if event.worker is self._footprint_card_worker:
            self._on_footprint_card_worker_state(event)
            return
        if event.worker is self._footprint_decision_worker:
            self._on_footprint_decision_worker_state(event)
            return
        if event.worker is self._footprint_finish_review_worker:
            self._on_footprint_finish_review_worker_state(event)
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            self._on_primary_success(event.worker.result)
        elif event.state == WorkerState.ERROR:
            if not self._generation_matches_worker(event.worker.result):
                return
            self._loading = False
            self._loaded_once = True
            message = str(event.worker.error) if event.worker.error else "load failed"
            self._paint_error(message)

    def _generation_matches_worker(self, payload: object) -> bool:
        if isinstance(payload, StatisticsLoadResult):
            return payload.generation == self._load_generation
        return True

    def _unwrap_primary(self, payload: object) -> StatisticsViewData | None:
        if isinstance(payload, StatisticsLoadResult):
            if payload.generation != self._load_generation or payload.kind != "primary":
                return None
            if isinstance(payload.payload, StatisticsViewData):
                return payload.payload
            return None
        if isinstance(payload, StatisticsViewData):
            return payload
        return None

    def _on_primary_success(self, payload: object) -> None:
        result = self._unwrap_primary(payload)
        if result is None:
            return
        if not self._result_matches_selection(result) or not self._result_paints_view(
            result, self._view
        ):
            # Keep the pane loading until a result for the current
            # selection lands. Clearing `_loading` here races the next
            # range cycle: settle waits see idle while a reload is still
            # debounced.
            self._loading = True
            self._schedule_load()
            return
        fingerprint = (
            result.project_stats.fingerprint
            if result.project_stats is not None
            else None
        )
        same_primary = (
            fingerprint is not None and fingerprint == self._primary_fingerprint
        )
        already_complete = same_primary and self._code_complete
        self._loading = False
        self._loaded_once = True
        self._last_error = ""
        self._stale_at = None
        current_identity = self._selection_identity()
        if already_complete and self._last_result is not None:
            self._cache_filter_options(self._last_result)
            self._update_heading()
            return
        if same_primary and self._last_result is not None:
            self._cache_filter_options(self._last_result)
            self._update_heading()
            if not self._code_complete:
                self._start_code_load(self._load_generation)
            return
        if (
            self._view == "projects"
            and result.project_stats is not None
            and self._last_result is not None
            and self._last_result.project_stats is not None
            and self._code_complete
            and "code" in self._last_result.project_stats.facets
            and self._painted_identity == current_identity
        ):
            fresh_primary = result.project_stats
            painted = self._last_result.project_stats
            merged = merge_project_code_stats(fresh_primary, painted)
            if merged is not None:
                self._unmerged_primary = result
                self._last_result = replace(result, project_stats=merged)
                self._primary_fingerprint = fingerprint
                self._code_complete = True
                self._painted_identity = current_identity
                self._cache_filter_options(self._last_result)
                self._paint_current_view()
                self._start_code_load(self._load_generation)
                self.call_after_refresh(self._repaint_loaded_view_after_layout)
                return
            self._unmerged_primary = result
            self._primary_fingerprint = fingerprint
            self._cache_filter_options(self._last_result)
            self._update_heading()
            self._start_code_load(self._load_generation)
            return
        self._unmerged_primary = None
        self._last_result = result
        self._primary_fingerprint = fingerprint
        self._painted_identity = current_identity
        if result.project_stats is not None and "code" in result.project_stats.facets:
            self._code_complete = True
            self._code_fingerprint = result.project_stats.fingerprint
        else:
            self._code_complete = False
            self._code_fingerprint = None
        self._apply_pending_footprint_highlight()
        self._cache_filter_options(result)
        self._paint_current_view()
        if self._view == "footprint":
            self._schedule_footprint_card()
        if (
            self._view == "projects"
            and result.project_stats is not None
            and not self._code_complete
        ):
            self._start_code_load(self._load_generation)
        # A newly lazy-mounted pane can finish a fast worker before its
        # first layout has assigned the final width. Statistics tiles are
        # width-sensitive Rich renderables, so repaint once after that
        # refresh rather than caching provisional mount dimensions.
        self.call_after_refresh(self._repaint_loaded_view_after_layout)

    def _on_code_worker_state(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            payload = event.worker.result
            if (
                isinstance(payload, StatisticsLoadResult)
                and payload.generation != self._load_generation
            ):
                return
            report = (
                payload.payload
                if isinstance(payload, StatisticsLoadResult)
                else payload
            )
            if not isinstance(report, ProjectStatsView):
                return
            self._apply_code_result(report)
        elif event.state == WorkerState.ERROR:
            payload = event.worker.result
            if (
                isinstance(payload, StatisticsLoadResult)
                and payload.generation != self._load_generation
            ):
                return
            message = (
                str(event.worker.error) if event.worker.error else "code load failed"
            )
            pending = self._unmerged_primary
            if (
                pending is not None
                and pending.project_stats is not None
                and self._view == "projects"
                and self._painted_matches_current()
            ):
                settled = replace(
                    pending.project_stats,
                    facets=pending.project_stats.facets | frozenset({"code"}),
                )
                self._last_result = replace(pending, project_stats=settled)
                self._unmerged_primary = None
                self._code_complete = True
                self._painted_identity = self._selection_identity()
                self._last_error = message
                self._cache_filter_options(self._last_result)
                self._update_heading()
                self._paint_current_view()
                return
            self._code_complete = True
            current = self._last_result
            if (
                current is not None
                and current.project_stats is not None
                and self._painted_matches_current()
            ):
                settled = replace(
                    current.project_stats,
                    facets=current.project_stats.facets | frozenset({"code"}),
                )
                self._last_result = replace(current, project_stats=settled)
                self._painted_identity = self._selection_identity()
                self._last_error = message
                self._update_heading()
                self._paint_current_view()

    def _apply_code_result(self, report: ProjectStatsView) -> None:
        if self._view != "projects":
            return
        if not self._painted_matches_current():
            return
        pending = self._unmerged_primary
        if pending is not None and pending.project_stats is not None:
            merged = merge_project_code_stats(pending.project_stats, report)
            if merged is None:
                self._schedule_load()
                return
            self._unmerged_primary = None
            self._code_complete = True
            self._code_fingerprint = report.fingerprint
            self._last_error = ""
            self._last_result = replace(pending, project_stats=merged)
            self._painted_identity = self._selection_identity()
            self._cache_filter_options(self._last_result)
            self._paint_current_view()
            return
        current = self._last_result
        if current is None or current.project_stats is None:
            return
        merged = merge_project_code_stats(current.project_stats, report)
        if merged is None:
            self._schedule_load()
            return
        first_code = not self._code_complete
        same_code = report.fingerprint == self._code_fingerprint
        self._code_complete = True
        self._code_fingerprint = report.fingerprint
        self._last_error = ""
        if same_code and not first_code:
            self._update_heading()
            return
        self._last_result = StatisticsViewData(
            view=current.view,
            selected_range=current.selected_range,
            generated_at=current.generated_at,
            views=current.views,
            project_filter=current.project_filter,
            macro_focus=current.macro_focus,
            project_display_snapshot=current.project_display_snapshot,
            perf=current.perf,
            project_stats=merged,
        )
        self._painted_identity = self._selection_identity()
        self._paint_current_view()

    def _cache_filter_options(self, result: StatisticsViewData) -> None:
        if result.project_filter is None:
            if result.project_stats is not None:
                self._project_filter_options = tuple(
                    project.key for project in result.project_stats.projects
                )
            elif result.views is not None:
                self._project_filter_options = tuple(
                    row.project_key for row in result.views.projects.projects
                )
            self._project_filter_options_ready = True
            self._maybe_seed_project_filter()
        if result.macro_focus is None and result.views is not None:
            self._macro_focus_options = tuple(
                row.name for row in result.views.macros.rows
            )

    def _repaint_loaded_view_after_layout(self) -> None:
        """Repaint a completed result after lazy-mount layout has settled."""
        if self._last_result is not None and self._is_active_tab():
            self._paint_current_view()

    def _result_matches_selection(self, result: StatisticsViewData) -> bool:
        """Whether *result* matches the current user selection.

        :class:`StatisticsPane` implements this.
        """
        raise NotImplementedError

    def _painted_matches_current(self) -> bool:
        """Whether the painted report belongs to the current user selection.

        :class:`StatisticsPane` implements this.
        """
        raise NotImplementedError

    def _selection_identity(self) -> tuple[object, ...]:
        """User selection without resolved bounds for revalidation checks.

        :class:`StatisticsPane` implements this.
        """
        raise NotImplementedError

    def _start_code_load(self, generation: int) -> None:
        """Launch the Code-facet worker for the current Projects report.

        :class:`StatisticsPane` implements this.
        """
        raise NotImplementedError


__all__ = ["StatisticsPaneWorkersMixin"]
