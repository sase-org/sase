"""Historical agent-activity statistics for the SASE Admin Center."""

from __future__ import annotations

from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, VerticalScroll
from textual.events import Click, Resize
from textual.message import Message
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import (
    StatisticsPaneKeymaps,
    build_statistics_bindings,
    load_keymap_registry,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import (
    DEFAULT_PRESET,
    PRESET_ORDER,
    PresetKey,
    StatsRange,
    parse_custom_range,
    resolve_preset,
)

from .statistics_pane_data import (
    PROJECTS_GROUP_ORDER,
    RUNTIME_GROUP_ORDER,
    VIEW_LABELS,
    VIEW_ORDER,
    ProjectsGroupBy,
    StatisticsView,
    StatisticsViewData,
    load_statistics_view,
)
from .statistics_pane_rendering import StatisticsPanePresentationBase

_ACCENT = "#FF87D7"
_REFRESH_INTERVAL_SECONDS = 30.0
_VIEW_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(view, VIEW_LABELS[view], _ACCENT) for view in VIEW_ORDER
)
OVERVIEW_TILE_TARGETS: tuple[tuple[str, StatisticsView], ...] = (
    ("Agents Run", "runs"),
    ("Success Rate", "runs"),
    ("Commits", "runs"),
    ("Plans Proposed", "plans_questions"),
    ("Questions", "plans_questions"),
)


class _OverviewTile(Static):
    """Mouse-only Overview summary that links to a detail view."""

    can_focus = False

    class Navigate(Message):
        """Request navigation to the view explained by this tile."""

        def __init__(self, view: StatisticsView) -> None:
            super().__init__()
            self.view = view

    def __init__(
        self,
        target_view: StatisticsView,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._target_view = target_view
        self.tooltip = f"Open {VIEW_LABELS[target_view]}"

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Navigate(self._target_view))


class _CustomRangeInput(Input):
    """Transient inline range editor owned by :class:`StatisticsPane`."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane._close_custom_range()

    def _pane(self) -> StatisticsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, StatisticsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class StatisticsPane(StatisticsPanePresentationBase):
    """Seven numeric Statistics views backed by durable agent activity."""

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
        self._runtime_group_by: RuntimeGroupBy = "tribe"
        self._projects_group_by: ProjectsGroupBy = "project"
        self._project_filter: str | None = None
        self._project_filter_options: tuple[str, ...] = ()
        self._auto_load = auto_load
        self._loading = False
        self._loaded_once = False
        self._worker: Worker[Any] | None = None
        self._refresh_timer: Any | None = None
        self._load_debouncer: DetailPanelDebouncer | None = None
        self._last_result: StatisticsViewData | None = None
        self._last_error = ""
        self._compact_scope = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="statistics-heading"):
            yield Static(self._heading_text(), id="statistics-title", markup=False)
            yield Static(self._status_text(), id="statistics-status", markup=False)
        yield PanelTabStrip(
            _VIEW_TABS,
            self._view,
            uppercase_active=True,
            id="statistics-views",
        )
        yield Static(
            self._description_text(),
            id="statistics-description",
            markup=False,
        )
        with Horizontal(id="statistics-scope"):
            yield Static(
                self._range_scope_text(),
                id="statistics-scope-range",
                classes="statistics-scope-part",
                markup=False,
            )
            yield Static(
                self._group_scope_text(),
                id="statistics-scope-group",
                classes="statistics-scope-part",
                markup=False,
            )
            yield Static(
                self._project_scope_text(),
                id="statistics-scope-project",
                classes="statistics-scope-part",
                markup=False,
            )
        yield _CustomRangeInput(
            placeholder=(
                "Custom range: 12h, 7d, 2w, YYYY-MM, "
                "YYYY-MM-DD..YYYY-MM-DD, or YYYY-MM-DD.."
            ),
            id="statistics-custom-range",
        )
        with Horizontal(id="statistics-tiles"):
            for index, (_caption, target_view) in enumerate(OVERVIEW_TILE_TARGETS):
                yield _OverviewTile(
                    target_view,
                    self._loading_panel("Loading", height=6),
                    id=f"statistics-tile-{index}",
                    classes="statistics-tile",
                )
        with VerticalScroll(id="statistics-body-scroll"):
            yield Static(
                self._loading_panel("Loading statistics", height=8),
                id="statistics-body",
            )
        yield Static(self._hints_text(), id="statistics-hints", markup=False)

    def on_mount(self) -> None:
        self.query_one("#statistics-custom-range", Input).display = False
        self._load_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_timer = self.set_interval(
            _REFRESH_INTERVAL_SECONDS,
            self._on_refresh_tick,
        )
        if self._is_active_tab():
            self._ensure_loaded()

    def on_unmount(self) -> None:
        if self._load_debouncer is not None:
            self._load_debouncer.cancel()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._worker is not None:
            self._worker.cancel()

    def on_resize(self, event: Resize) -> None:
        """Update only scope copy when crossing the compact-width threshold."""
        compact = event.size.width < self._SCOPE_COMPACT_BELOW_WIDTH
        if compact == self._compact_scope:
            return
        self._compact_scope = compact
        self._update_scope()

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

    def action_prev_view(self) -> None:
        """Select the previous Statistics view."""
        self._cycle_view(-1)

    def action_next_view(self) -> None:
        """Select the next Statistics view."""
        self._cycle_view(1)

    def action_cycle_range(self) -> None:
        """Cycle through Today, 24h, 7d, 30d, 90d, and All."""
        if self._preset_key is None:
            next_key = PRESET_ORDER[0]
        else:
            index = PRESET_ORDER.index(self._preset_key)
            next_key = PRESET_ORDER[(index + 1) % len(PRESET_ORDER)]
        self._preset_key = next_key
        self._custom_range_value = None
        self._range = resolve_preset(next_key)
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
        if self._view == "runtime":
            index = RUNTIME_GROUP_ORDER.index(self._runtime_group_by)
            self._runtime_group_by = RUNTIME_GROUP_ORDER[
                (index + 1) % len(RUNTIME_GROUP_ORDER)
            ]
            self._selection_changed(reload=True)
        elif self._view == "projects":
            index = PROJECTS_GROUP_ORDER.index(self._projects_group_by)
            self._projects_group_by = PROJECTS_GROUP_ORDER[
                (index + 1) % len(PROJECTS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)

    def action_cycle_project_filter(self) -> None:
        """Cycle All → ranked projects in range → All."""
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
        self._project_filter = cycle[(index + 1) % len(cycle)]
        self._selection_changed(reload=True)

    def action_refresh(self) -> None:
        """Coalesce a manual refresh through the worker-backed load path."""
        self._schedule_load()

    @on(PanelTabStrip.TabClicked)
    def _on_view_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id in VIEW_ORDER:
            self._set_view(cast(StatisticsView, event.tab_id))

    @on(_OverviewTile.Navigate)
    def _on_overview_tile_navigate(self, event: _OverviewTile.Navigate) -> None:
        self._set_view(event.view)

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

    def _close_custom_range(self) -> None:
        try:
            self.query_one("#statistics-custom-range", Input).display = False
        except Exception:
            pass
        self.focus()

    def _cycle_view(self, delta: int) -> None:
        index = VIEW_ORDER.index(self._view)
        self._set_view(VIEW_ORDER[(index + delta) % len(VIEW_ORDER)])

    def _set_view(self, view: StatisticsView) -> None:
        if view == self._view:
            return
        self._view = view
        try:
            self.query_one("#statistics-views", PanelTabStrip).set_active_tab(view)
        except Exception:
            pass
        self._selection_changed(reload=False)

    def _selection_changed(self, *, reload: bool) -> None:
        self._last_error = ""
        self._update_heading()
        self._update_hints()
        if reload:
            self._schedule_load()
        else:
            self._paint_current_view()

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
        runtime_group_by = self._runtime_group_by
        project_filter = self._project_filter
        self._loading = True
        self._last_error = ""
        self._update_heading()
        if self._last_result is None:
            self._paint_loading()

        def task() -> StatisticsViewData:
            return load_statistics_view(
                view,
                selected_range,
                runtime_group_by,
                project_filter,
            )

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
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
                or result.runtime_group_by != self._runtime_group_by
                or result.project_filter != self._project_filter
            ):
                self._schedule_load()
                return
            self._last_result = result
            if result.project_filter is None:
                self._project_filter_options = tuple(
                    row.project_key for row in result.views.projects.projects
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


__all__ = ["OVERVIEW_TILE_TARGETS", "StatisticsPane"]
