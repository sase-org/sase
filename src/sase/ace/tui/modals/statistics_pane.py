"""Historical agent-activity statistics for the SASE Admin Center."""

from __future__ import annotations

from typing import Any

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
from sase.current_project import resolve_current_project
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

from ._statistics_pane_load import StatisticsLoadResult
from .statistics_pane_workers import StatisticsPaneWorkersMixin

_REFRESH_INTERVAL_SECONDS = 30.0
_PRIMARY_WORKER_GROUP = "statistics-primary"
_CODE_WORKER_GROUP = "statistics-code"


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


class StatisticsPane(StatisticsPaneWorkersMixin):
    """Nine Statistics views backed by durable local activity reports."""

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
        self._footprint_lens = "map"
        self._footprint_actor = "you"
        self._footprint_area: str | None = None
        self._footprint_selected_index = 0
        self._footprint_card: dict[str, Any] | None = None
        self._footprint_card_for: tuple[str, str] | None = None
        self._footprint_card_error = ""
        self._footprint_card_loading = False
        self._footprint_card_generation = 0
        self._footprint_card_worker: Worker[Any] | None = None
        self._footprint_card_debouncer: DetailPanelDebouncer | None = None
        self._footprint_pending_highlight: str | None = None
        self._footprint_decision_worker: Worker[Any] | None = None
        self._footprint_finish_review_worker: Worker[Any] | None = None
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
        self._inflight_identity: tuple[object, ...] | None = None
        self._painted_identity: tuple[object, ...] | None = None
        self._unmerged_primary: StatisticsViewData | None = None
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
        self._footprint_card_debouncer = DetailPanelDebouncer(self.app)
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
        if self._footprint_card_debouncer is not None:
            self._footprint_card_debouncer.cancel()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._worker is not None:
            self._worker.cancel()
        if self._code_worker is not None:
            self._code_worker.cancel()
        if self._footprint_card_worker is not None:
            self._footprint_card_worker.cancel()
        if self._footprint_decision_worker is not None:
            self._footprint_decision_worker.cancel()
        if self._footprint_finish_review_worker is not None:
            self._footprint_finish_review_worker.cancel()
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
        elif self._view in {"projects", "footprint"} and self._last_result is not None:
            self._paint_current_view()

    def focus_default(self) -> None:
        """Focus this key-driven pane and lazily perform its first load."""
        self.focus()
        self._ensure_loaded()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause pending work while another Admin Center tab is active."""
        if active:
            self._ensure_loaded()
        else:
            if self._load_debouncer is not None:
                self._load_debouncer.cancel()
            if self._footprint_card_debouncer is not None:
                self._footprint_card_debouncer.cancel()

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
        selection: tuple[object, ...] = (
            self._view,
            self._range,
            self._project_filter,
            self._macro_focus,
            self._perf_group_by if self._view == "perf" else None,
        )
        if self._view == "footprint":
            return (
                *selection,
                self._footprint_lens,
                self._footprint_actor,
                self._footprint_area,
            )
        return selection

    def _selection_identity(self) -> tuple[object, ...]:
        """User selection without resolved bounds for revalidation checks."""
        identity: tuple[object, ...] = (
            self._view,
            self._preset_key,
            self._custom_range_value if self._preset_key is None else None,
            self._project_filter,
            self._macro_focus,
            self._perf_group_by if self._view == "perf" else None,
        )
        if self._view == "footprint":
            return (
                *identity,
                self._footprint_lens,
                self._footprint_actor,
                self._footprint_area,
            )
        return identity

    def _painted_matches_current(self) -> bool:
        """Whether the painted report belongs to the current user selection."""
        if self._painted_identity is not None:
            return self._painted_identity == self._selection_identity()
        current = self._last_result
        if current is None:
            return False
        try:
            return self._result_matches_selection(current)
        except Exception:
            return False

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
                    and self._view != "footprint"
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
            and (
                self._view != "footprint"
                or (
                    result.footprint is not None
                    and result.footprint_lens == self._footprint_lens
                    and result.footprint_actor == self._footprint_actor
                    and result.footprint_area == self._footprint_area
                )
            )
        )

    def _start_load(self) -> None:
        if not self._is_active_tab():
            return
        self._range = self._resolve_current_range()
        selection = self._current_selection()
        identity = self._selection_identity()
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
        footprint_lens = self._footprint_lens
        footprint_actor = self._footprint_actor
        footprint_area = self._footprint_area
        preset = self._preset_key
        self._load_generation += 1
        generation = self._load_generation
        self._inflight_selection = selection
        self._inflight_identity = identity
        if view == "footprint":
            # A new report invalidates any in-flight evidence card fetch:
            # the rows it was fetched for may no longer be selected.
            self._footprint_card_generation += 1
        if self._code_worker is not None:
            self._code_worker.cancel()
            self._code_worker = None
        self._loading = True
        self._last_error = ""
        self._update_heading()
        matching = (
            self._last_result is not None
            and self._painted_identity == identity
            and self._result_paints_view(self._last_result, view)
        )
        if not matching:
            self._stale_at = None
            self._paint_loading()

        def task() -> StatisticsLoadResult:
            if view == "footprint":
                loaded = load_statistics_view(
                    view,
                    selected_range,
                    project_filter,
                    macro_focus,
                    footprint_lens=footprint_lens,
                    footprint_actor=footprint_actor,
                    footprint_area=footprint_area,
                )
            else:
                loaded = load_statistics_view(
                    view,
                    selected_range,
                    project_filter,
                    macro_focus,
                    perf_group_by=perf_group_by,
                    preset=preset,
                )
            return StatisticsLoadResult(
                generation,
                "primary",
                loaded,
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

        def task() -> StatisticsLoadResult:
            return StatisticsLoadResult(
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


__all__ = ["StatisticsPane"]
