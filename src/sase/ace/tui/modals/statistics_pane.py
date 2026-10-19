"""Historical agent-activity statistics for the SASE Admin Center."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from textual.binding import BindingsMap
from textual.events import Resize
from textual.widgets import Input
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import (
    StatisticsPaneKeymaps,
    build_statistics_bindings,
    load_keymap_registry,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.current_project import CurrentProject, resolve_current_project
from sase.stats.loader import StatisticsViewData, load_statistics_view
from sase.stats.project import ProjectStatsView
from sase.stats.ranges import (
    DEFAULT_PRESET,
    PresetKey,
    StatsRange,
    parse_stats_range,
    resolve_preset,
)
from sase.stats.registry import (
    MacrosGroupBy,
    PerfGroupBy,
    ProjectsGroupBy,
    StatisticsView,
)

from .statistics_pane_actions import StatisticsPaneActionsMixin
from .statistics_pane_project_merge import merge_project_code_stats

_REFRESH_INTERVAL_SECONDS = 30.0
_PRIMARY_WORKER_GROUP = "statistics-primary"
_CODE_WORKER_GROUP = "statistics-code"


@dataclass(frozen=True, slots=True)
class _StatisticsLoadResult:
    """Worker payload carrying the selection generation that produced it."""

    generation: int
    kind: Literal["primary", "code"]
    payload: StatisticsViewData | ProjectStatsView


def _load_project_code_stats(
    selected_range: StatsRange,
    project_filter: str | None = None,
    *,
    preset: str | None = None,
) -> ProjectStatsView:
    """Load the Code facet for an already-painted Projects report.

    Visual fixtures patch this seam so snapshot tests never read real repos.
    """
    result = load_statistics_view(
        "projects",
        selected_range,
        project_filter,
        facets={"code"},
        preset=preset,
    )
    if result.project_stats is None:
        raise RuntimeError("project code load returned no report")
    return result.project_stats


class StatisticsPane(StatisticsPaneActionsMixin):
    """Eight numeric Statistics views backed by durable agent activity."""

    can_focus = True
    BINDINGS = []

    def __init__(
        self,
        *,
        auto_load: bool = True,
        keymaps: StatisticsPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._keymaps = keymaps or load_keymap_registry({}).statistics
        self._bindings = BindingsMap(build_statistics_bindings(self._keymaps))
        self._view: StatisticsView = "overview"
        self._preset_key: PresetKey | None = DEFAULT_PRESET
        self._custom_range_value: str | None = None
        self._range = resolve_preset(DEFAULT_PRESET)
        self._projects_group_by: ProjectsGroupBy = "project"
        self._macros_group_by: MacrosGroupBy = "usage"
        self._perf_group_by: PerfGroupBy = "subsystem"
        self._project_filter: str | None = None
        self._project_filter_options: tuple[str, ...] = ()
        self._project_filter_options_ready = False
        self._project_filter_seeded = False
        self._current_project_resolved = False
        self._current_project_key: str | None = None
        self._current_project_seed_worker: Worker[Any] | None = None
        self._macro_focus: str | None = None
        self._macro_focus_options: tuple[str, ...] = ()
        self._auto_load = auto_load
        self._loading = False
        self._loaded_once = False
        self._worker: Worker[Any] | None = None
        self._code_worker: Worker[Any] | None = None
        self._refresh_timer: Any | None = None
        self._load_debouncer: DetailPanelDebouncer | None = None
        self._last_result: StatisticsViewData | None = None
        self._last_error = ""
        self._stale_at: float | None = None
        self._load_generation = 0
        self._inflight_selection: tuple[object, ...] | None = None
        self._primary_fingerprint: str | None = None
        self._code_fingerprint: str | None = None
        self._code_complete = False
        self._compact_scope = False
        self._runners_stacked = False
        self._perf_stacked = False
        self._pending_view_select = False

    def on_mount(self) -> None:
        self.query_one("#statistics-custom-range", Input).display = False
        self._load_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_timer = self.set_interval(
            _REFRESH_INTERVAL_SECONDS,
            self._on_refresh_tick,
        )
        if self._is_active_tab():
            self._ensure_loaded()
        self._maybe_start_current_project_seed()

    def on_unmount(self) -> None:
        if self._load_debouncer is not None:
            self._load_debouncer.cancel()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._worker is not None:
            self._worker.cancel()
        if self._code_worker is not None:
            self._code_worker.cancel()
        if self._current_project_seed_worker is not None:
            self._current_project_seed_worker.cancel()

    def on_resize(self, event: Resize) -> None:
        """Repaint only presentation whose responsive threshold changed."""
        compact = event.size.width < self._SCOPE_COMPACT_BELOW_WIDTH
        if compact != self._compact_scope:
            self._compact_scope = compact
            self._update_scope()

        runners_stacked = event.size.width < self._RUNNERS_STACK_BELOW_WIDTH
        perf_stacked = event.size.width < self._PERF_STACK_BELOW_WIDTH
        runners_changed = runners_stacked != self._runners_stacked
        perf_changed = perf_stacked != self._perf_stacked
        if runners_changed:
            self._runners_stacked = runners_stacked
        if perf_changed:
            self._perf_stacked = perf_stacked
        if self._last_result is None:
            return
        if runners_changed and self._view == "runners":
            self._paint_current_view()
        elif perf_changed and self._view == "perf":
            self._paint_current_view()
        elif self._view == "projects" and self._last_result is not None:
            self._paint_current_view()

    def focus_default(self) -> None:
        """Focus this key-driven pane and lazily perform its first load."""
        self.focus()
        self._ensure_loaded()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause pending work while another Admin Center tab is active."""
        if active:
            self._ensure_loaded()
        elif self._load_debouncer is not None:
            self._load_debouncer.cancel()

    def _ensure_loaded(self) -> None:
        if self._auto_load and not self._loaded_once and not self._loading:
            self._start_load()

    def _schedule_load(self) -> None:
        if not self._is_active_tab():
            return
        if self._load_debouncer is None:
            self._start_load()
            return
        self._load_debouncer.schedule(self._start_load)

    def _on_refresh_tick(self) -> None:
        """Thin synchronous timer callback; real work stays in a worker."""
        if self._is_active_tab():
            self._schedule_load()

    def _resolve_current_range(self) -> StatsRange:
        if self._preset_key is not None:
            return resolve_preset(self._preset_key)
        if self._custom_range_value is not None:
            return parse_stats_range(self._custom_range_value)
        return self._range

    def _current_selection(self) -> tuple[object, ...]:
        return (
            self._view,
            self._range,
            self._project_filter,
            self._macro_focus,
            self._perf_group_by if self._view == "perf" else None,
        )

    def _worker_is_running(self, worker: Worker[Any] | None) -> bool:
        return worker is not None and worker.state in (
            WorkerState.PENDING,
            WorkerState.RUNNING,
        )

    def _result_matches_selection(self, result: StatisticsViewData) -> bool:
        return (
            result.selected_range == self._range
            and result.project_filter == self._project_filter
            and result.macro_focus == self._macro_focus
            and (
                result.view == self._view
                or (
                    self._view != "projects"
                    and result.view != "projects"
                    and result.views is not None
                )
            )
            and (
                self._view != "perf"
                or (
                    result.perf is not None
                    and result.perf.group_by == self._perf_group_by
                )
            )
        )

    def _start_load(self) -> None:
        if not self._is_active_tab():
            return
        self._range = self._resolve_current_range()
        selection = self._current_selection()
        if (
            self._worker_is_running(self._worker)
            and self._inflight_selection == selection
        ):
            return
        view = self._view
        selected_range = self._range
        project_filter = self._project_filter
        macro_focus = self._macro_focus
        perf_group_by = self._perf_group_by
        preset = self._preset_key
        self._load_generation += 1
        generation = self._load_generation
        self._inflight_selection = selection
        if self._code_worker is not None:
            self._code_worker.cancel()
            self._code_worker = None
        self._loading = True
        self._last_error = ""
        self._update_heading()
        matching = (
            self._last_result is not None
            and self._result_matches_selection(self._last_result)
            and self._result_paints_view(self._last_result, view)
        )
        if not matching:
            self._stale_at = None
            self._paint_loading()

        def task() -> _StatisticsLoadResult:
            return _StatisticsLoadResult(
                generation,
                "primary",
                load_statistics_view(
                    view,
                    selected_range,
                    project_filter,
                    macro_focus,
                    perf_group_by=perf_group_by,
                    preset=preset,
                ),
            )

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_PRIMARY_WORKER_GROUP,
            exit_on_error=False,
        )

    def _start_code_load(self, generation: int) -> None:
        if self._view != "projects" or generation != self._load_generation:
            return
        if self._worker_is_running(self._code_worker):
            return
        selected_range = self._range
        project_filter = self._project_filter
        preset = self._preset_key

        def task() -> _StatisticsLoadResult:
            return _StatisticsLoadResult(
                generation,
                "code",
                _load_project_code_stats(
                    selected_range,
                    project_filter,
                    preset=preset,
                ),
            )

        self._code_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_CODE_WORKER_GROUP,
            exit_on_error=False,
        )

    def _maybe_start_current_project_seed(self) -> None:
        """Kick a one-shot worker resolving the current project, if enabled."""
        settings = getattr(self.app, "_current_project_settings", None)
        if settings is not None and not getattr(settings, "seed_filters", True):
            self._current_project_resolved = True
            return
        self._current_project_seed_worker = self.run_worker(
            resolve_current_project,
            thread=True,
            exclusive=False,
            exit_on_error=False,
            group="current-project-seed",
        )

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
        if isinstance(payload, _StatisticsLoadResult):
            return payload.generation == self._load_generation
        return True

    def _unwrap_primary(self, payload: object) -> StatisticsViewData | None:
        if isinstance(payload, _StatisticsLoadResult):
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
        self._last_result = result
        self._primary_fingerprint = fingerprint
        if result.project_stats is not None and "code" in result.project_stats.facets:
            self._code_complete = True
            self._code_fingerprint = result.project_stats.fingerprint
        else:
            self._code_complete = False
            self._code_fingerprint = None
        self._cache_filter_options(result)
        self._paint_current_view()
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
                isinstance(payload, _StatisticsLoadResult)
                and payload.generation != self._load_generation
            ):
                return
            report = (
                payload.payload
                if isinstance(payload, _StatisticsLoadResult)
                else payload
            )
            if not isinstance(report, ProjectStatsView):
                return
            self._apply_code_result(report)
        elif event.state == WorkerState.ERROR:
            payload = event.worker.result
            if (
                isinstance(payload, _StatisticsLoadResult)
                and payload.generation != self._load_generation
            ):
                return
            self._code_complete = True
            current = self._last_result
            if (
                current is not None
                and current.project_stats is not None
                and self._result_matches_selection(current)
            ):
                settled = replace(
                    current.project_stats,
                    facets=current.project_stats.facets | frozenset({"code"}),
                )
                self._last_result = replace(current, project_stats=settled)
                self._last_error = (
                    str(event.worker.error)
                    if event.worker.error
                    else "code load failed"
                )
                self._update_heading()
                self._paint_current_view()

    def _apply_code_result(self, report: ProjectStatsView) -> None:
        current = self._last_result
        if (
            current is None
            or current.project_stats is None
            or not self._result_matches_selection(current)
            or self._view != "projects"
        ):
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


__all__ = ["StatisticsPane"]
