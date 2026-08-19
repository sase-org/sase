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
from sase.current_project import CurrentProject, resolve_current_project
from sase.stats.ranges import (
    DEFAULT_PRESET,
    PresetKey,
    StatsRange,
    parse_custom_range,
    resolve_preset,
)

from .statistics_pane_actions import StatisticsPaneActionsMixin
from .statistics_pane_data import (
    PerfGroupBy,
    ProjectsGroupBy,
    StatisticsView,
    StatisticsViewData,
    XPromptsGroupBy,
    load_statistics_view,
)

_REFRESH_INTERVAL_SECONDS = 30.0


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
        self._xprompts_group_by: XPromptsGroupBy = "usage"
        self._perf_group_by: PerfGroupBy = "subsystem"
        self._project_filter: str | None = None
        self._project_filter_options: tuple[str, ...] = ()
        self._project_filter_options_ready = False
        self._project_filter_seeded = False
        self._current_project_resolved = False
        self._current_project_key: str | None = None
        self._current_project_seed_worker: Worker[Any] | None = None
        self._xprompt_focus: str | None = None
        self._xprompt_focus_options: tuple[str, ...] = ()
        self._auto_load = auto_load
        self._loading = False
        self._loaded_once = False
        self._worker: Worker[Any] | None = None
        self._refresh_timer: Any | None = None
        self._load_debouncer: DetailPanelDebouncer | None = None
        self._last_result: StatisticsViewData | None = None
        self._last_error = ""
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
            return parse_custom_range(self._custom_range_value)
        return self._range

    def _start_load(self) -> None:
        if not self._is_active_tab():
            return
        self._range = self._resolve_current_range()
        view = self._view
        selected_range = self._range
        project_filter = self._project_filter
        xprompt_focus = self._xprompt_focus
        perf_group_by = self._perf_group_by
        self._loading = True
        self._last_error = ""
        self._update_heading()
        if self._last_result is None:
            self._paint_loading()

        def task() -> StatisticsViewData:
            return load_statistics_view(
                view,
                selected_range,
                project_filter,
                xprompt_focus,
                perf_group_by=perf_group_by,
            )

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
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
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            self._loaded_once = True
            result = event.worker.result
            if not isinstance(result, StatisticsViewData):
                self._paint_error("statistics worker returned no result")
                return
            if (
                result.view != self._view
                or result.selected_range != self._range
                or result.project_filter != self._project_filter
                or result.xprompt_focus != self._xprompt_focus
                or (
                    self._view == "perf"
                    and (
                        result.perf is None
                        or result.perf.group_by != self._perf_group_by
                    )
                )
            ):
                self._schedule_load()
                return
            self._last_result = result
            if result.project_filter is None:
                self._project_filter_options = tuple(
                    row.project_key for row in result.views.projects.projects
                )
                self._project_filter_options_ready = True
                self._maybe_seed_project_filter()
            if result.xprompt_focus is None:
                self._xprompt_focus_options = tuple(
                    row.name for row in result.views.xprompts.rows
                )
            self._paint_current_view()
            # A newly lazy-mounted pane can finish a fast worker before its
            # first layout has assigned the final width. Statistics tiles are
            # width-sensitive Rich renderables, so repaint once after that
            # refresh rather than caching provisional mount dimensions.
            self.call_after_refresh(self._repaint_loaded_view_after_layout)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loaded_once = True
            message = str(event.worker.error) if event.worker.error else "load failed"
            self._paint_error(message)

    def _repaint_loaded_view_after_layout(self) -> None:
        """Repaint a completed result after lazy-mount layout has settled."""
        if self._last_result is not None and self._is_active_tab():
            self._paint_current_view()


__all__ = ["StatisticsPane"]
