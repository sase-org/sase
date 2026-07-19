"""Historical agent-activity statistics for the SASE Admin Center."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import (
    StatisticsPaneKeymaps,
    build_statistics_bindings,
    load_keymap_registry,
    statistics_help_bindings,
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
from sase.telemetry.render import format_duration, render_stat_tile

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
from .statistics_pane_projects import StatisticsProjectsRenderingMixin

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"
_RED = "#FF5F5F"
_REFRESH_INTERVAL_SECONDS = 30.0
_PROJECTS_GROUP_LABELS: dict[ProjectsGroupBy, str] = {
    "project": "By Project",
    "changespec": "By ChangeSpec",
    "drilldown": "Project → ChangeSpec",
}
_VIEW_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(view, VIEW_LABELS[view], _ACCENT) for view in VIEW_ORDER
)


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


class StatisticsPane(StatisticsProjectsRenderingMixin, Vertical):
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

    def compose(self) -> ComposeResult:
        yield Static(self._heading_text(), id="statistics-title", markup=False)
        yield PanelTabStrip(
            _VIEW_TABS,
            self._view,
            uppercase_active=True,
            id="statistics-views",
        )
        yield _CustomRangeInput(
            placeholder=(
                "Custom range: 12h, 7d, 2w, YYYY-MM, "
                "YYYY-MM-DD..YYYY-MM-DD, or YYYY-MM-DD.."
            ),
            id="statistics-custom-range",
        )
        with Horizontal(id="statistics-tiles"):
            for index in range(5):
                yield Static(
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
                row.project for row in self._last_result.views.projects.projects
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
                    row.project for row in result.views.projects.projects
                )
            self._paint_current_view()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loaded_once = True
            message = str(event.worker.error) if event.worker.error else "load failed"
            self._paint_error(message)

    def _paint_loading(self) -> None:
        self._set_tiles_visible(self._view == "overview")
        if self._view == "overview":
            tile_width = self._tile_width()
            for index in range(5):
                self._update_static(
                    f"#statistics-tile-{index}",
                    self._loading_panel("Loading", width=tile_width, height=6),
                )
        self._update_static(
            "#statistics-body",
            self._loading_panel(
                "Loading statistics",
                width=max(48, int(self.size.width or 100) - 2),
                height=max(8, int(self.size.height or 24) - 11),
            ),
        )

    def _paint_current_view(self) -> None:
        result = self._last_result
        self._update_heading()
        self._set_tiles_visible(self._view == "overview")
        if result is None:
            self._paint_loading()
            return
        if result.views.empty:
            self._set_tiles_visible(False)
            self._update_static(
                "#statistics-body",
                Panel(
                    Align.center(
                        Text(
                            "No agent runs were recorded in the selected range.",
                            style="dim italic",
                        ),
                        vertical="middle",
                    ),
                    title="Statistics",
                    border_style="#444444",
                    height=max(8, int(self.size.height or 24) - 10),
                ),
            )
            return
        if self._view == "overview":
            self._paint_overview_tiles(result)
        self._update_static("#statistics-body", self._view_renderable(result))

    def _paint_overview_tiles(self, result: StatisticsViewData) -> None:
        overview = result.views.overview
        tile_width = self._tile_width()
        bucket_values = tuple(float(bucket.runs) for bucket in overview.buckets)
        delta = (
            overview.runs_delta_ratio * 100.0
            if overview.runs_delta_ratio is not None
            else None
        )
        tiles = (
            render_stat_tile(
                f"{overview.agents_run}\n✓ {overview.completed}  × {overview.failed}",
                caption="Agents Run",
                width=tile_width,
                height=6,
                key="agents",
                delta=delta,
                sparkline=bucket_values,
            ),
            render_stat_tile(
                overview.success_rate * 100.0,
                caption="Success Rate",
                width=tile_width,
                height=6,
                key="success",
                value_format="percent",
            ),
            render_stat_tile(
                f"{overview.commits}\n{overview.committing_agents} agents",
                caption="Commits",
                width=tile_width,
                height=6,
                key="commits",
            ),
            render_stat_tile(
                f"{overview.plans_proposed}\n{overview.epic_plans} epic · "
                f"{overview.tale_plans} tale",
                caption="Plans Proposed",
                width=tile_width,
                height=6,
                key="plans",
            ),
            render_stat_tile(
                f"{overview.questions}\n{overview.question_sessions} sessions",
                caption="Questions",
                width=tile_width,
                height=6,
                key="questions",
            ),
        )
        for index, renderable in enumerate(tiles):
            self._update_static(f"#statistics-tile-{index}", renderable)

    def _view_renderable(self, result: StatisticsViewData) -> Any:
        views = result.views
        if self._view == "overview":
            return self._overview_renderable(views.overview)
        if self._view == "runs":
            return self._runs_renderable(views.runs)
        if self._view == "projects":
            return self._projects_renderable(views.projects)
        if self._view == "providers":
            return self._providers_renderable(views.providers)
        if self._view == "runtime":
            return self._runtime_renderable(views.runtime)
        if self._view == "activity":
            return self._activity_renderable(views.activity)
        return self._plans_questions_renderable(views.plans_questions)

    def _overview_renderable(self, overview: Any) -> Group:
        buckets = Table(box=box.SIMPLE, expand=True, show_header=True)
        buckets.add_column("Bucket", style="bold")
        buckets.add_column("Runs", justify="right", style=_CYAN)
        buckets.add_column("Scale", ratio=1)
        maximum = max((bucket.runs for bucket in overview.buckets), default=0)
        for bucket in overview.buckets:
            buckets.add_row(
                bucket.label,
                str(bucket.runs),
                self._share_bar(bucket.runs, maximum),
            )
        providers = self._count_table(
            "Provider", overview.top_providers, include_share=True
        )
        skills = Table(box=box.SIMPLE, expand=True)
        skills.add_column("Skill", style="bold")
        skills.add_column("Uses", justify="right", style=_CYAN)
        skills.add_column("Agents", justify="right")
        for row in overview.top_skills:
            skills.add_row(row.label, str(row.count), str(row.distinct_agents))
        projects = Table(box=box.SIMPLE, expand=True)
        projects.add_column("Project", style="bold", ratio=1)
        projects.add_column("Runs", justify="right", style=_CYAN)
        projects.add_column("Success", justify="right", style=_GREEN)
        for row in overview.top_projects:
            projects.add_row(
                self._project_cell(row.project),
                str(row.runs),
                self._percent(row.success_rate),
            )
        mini_table_width = max(24, (max(60, int(self.size.width or 100)) - 4) // 3)
        return Group(
            Panel(buckets, title="Runs over time", border_style=_ACCENT),
            Columns(
                (
                    Panel(providers, title="Top providers", border_style=_CYAN),
                    Panel(skills, title="Top skills", border_style=_GOLD),
                    Panel(projects, title="Top projects", border_style=_GREEN),
                ),
                equal=True,
                expand=True,
                width=mini_table_width,
            ),
        )

    def _runs_renderable(self, runs: Any) -> Group:
        outcomes = self._count_table("Outcome", runs.outcomes, include_share=True)
        lifecycle = Text()
        lifecycle.append(f"In progress  {runs.in_progress}", style=_CYAN)
        lifecycle.append("    ")
        lifecycle.append(f"Waiting  {runs.waiting}", style=_GOLD)
        lifecycle.append("    ")
        lifecycle.append(f"Retry chains  {runs.retry_chains}")
        lifecycle.append(f"  ·  attempts  {runs.retry_attempts}")
        lifecycle.append(f"  ·  kills  {runs.retry_kills}", style=_RED)
        commit_summary = Text(
            f"{runs.commits} commits  ·  {runs.committing_agents} committing agents  ·  "
            f"{runs.average_commits_per_committing_agent:.2f} average per committing agent"
        )
        distribution = self._distribution_table("Commits", runs.commit_distribution)
        repos = self._count_table("Repository", runs.top_repos)
        return Group(
            Panel(outcomes, title="Outcomes", border_style=_ACCENT),
            Panel(lifecycle, title="Run state & retries", border_style=_CYAN),
            Panel(commit_summary, title="Commit attribution", border_style=_GREEN),
            Columns(
                (
                    Panel(
                        distribution,
                        title="Commits per agent",
                        border_style=_GOLD,
                    ),
                    Panel(repos, title="Top target repos", border_style=_CYAN),
                ),
                equal=True,
                expand=True,
            ),
        )

    def _providers_renderable(self, providers: Any) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Provider", style="bold")
        table.add_column("Model")
        table.add_column("Effort")
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Share", justify="right")
        table.add_column("Success", justify="right", style=_GREEN)
        table.add_column("Avg runtime", justify="right")
        for row in providers.rows:
            table.add_row(
                row.provider,
                row.model,
                row.effort,
                str(row.runs),
                self._percent(row.share),
                self._percent(row.success_rate),
                "—"
                if row.mean_runtime_seconds is None
                else format_duration(row.mean_runtime_seconds),
            )
        return Panel(table, title="Provider → model → effort", border_style=_ACCENT)

    def _runtime_renderable(self, runtime: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(runtime.group_by.title(), style="bold", ratio=1)
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Total", justify="right")
        table.add_column("Mean", justify="right")
        table.add_column("p50", justify="right")
        table.add_column("p95", justify="right")
        table.add_column("Max", justify="right")
        table.add_column("Share", justify="right")
        table.add_column("Scale")
        for row in runtime.rows:
            table.add_row(
                row.group,
                str(row.runs),
                format_duration(row.total_seconds),
                format_duration(row.mean_seconds),
                format_duration(row.p50_seconds),
                format_duration(row.p95_seconds),
                format_duration(row.max_seconds),
                self._percent(row.share),
                self._share_bar(row.share, 1.0, width=10),
            )
        footnote = Text(
            f"In progress: {runtime.in_progress} (excluded from duration math)",
            style="dim",
        )
        return Group(
            Panel(
                table,
                title=f"Runtime grouped by {runtime.group_by}",
                border_style=_ACCENT,
            ),
            footnote,
        )

    def _activity_renderable(self, activity: Any) -> Columns:
        skills = self._activity_table("Skill", activity.skills)
        memories = self._activity_table("Memory", activity.memories)
        workspaces = Table(box=box.SIMPLE, expand=True)
        workspaces.add_column("Workspace", style="bold")
        workspaces.add_column("Runs", justify="right", style=_CYAN)
        for row in activity.workspaces:
            workspaces.add_row(f"{row.project} · {row.workspace_num}", str(row.runs))
        return Columns(
            (
                Panel(skills, title="Skills", border_style=_ACCENT),
                Panel(memories, title="Memories", border_style=_CYAN),
                Panel(workspaces, title="Workspaces", border_style=_GOLD),
            ),
            equal=True,
            expand=True,
        )

    def _plans_questions_renderable(self, view: Any) -> Columns:
        unscoped_suffix = " (all projects)" if self._project_filter else ""
        plans_summary = Text(
            f"Proposed  {view.plans_proposed}  ·  Approved  {view.plans_approved}  ·  "
            f"Rejected  {view.plans_rejected}  ·  Pending  {view.plans_pending}"
        )
        tiers = self._count_table(f"Tier{unscoped_suffix}", view.plan_tiers)
        phases = self._distribution_table(
            f"Phases{unscoped_suffix}", view.phases_per_epic
        )
        questions_summary = Text(
            f"Sessions  {view.question_sessions}  ·  Asking agents  {view.asking_agents}"
        )
        question_summary_rows: tuple[Text, ...]
        if self._project_filter:
            question_summary_rows = (
                questions_summary,
                Text(f"Questions{unscoped_suffix}: {view.questions}"),
            )
        else:
            questions_summary.append(f"  ·  Questions  {view.questions}")
            question_summary_rows = (questions_summary,)
        question_sizes = self._distribution_table(
            f"Questions{unscoped_suffix}", view.questions_per_session
        )
        return Columns(
            (
                Panel(
                    Group(
                        plans_summary,
                        tiers,
                        Text(
                            "Mean phases per epic"
                            f"{unscoped_suffix}: {view.mean_phases_per_epic:.2f}",
                            style="dim",
                        ),
                        phases,
                    ),
                    title="Plans",
                    border_style=_ACCENT,
                ),
                Panel(
                    Group(
                        *question_summary_rows,
                        Text(
                            "Mean questions per session"
                            f"{unscoped_suffix}: "
                            f"{view.mean_questions_per_session:.2f}",
                            style="dim",
                        ),
                        question_sizes,
                    ),
                    title="Questions",
                    border_style=_CYAN,
                ),
            ),
            equal=True,
            expand=True,
        )

    @staticmethod
    def _count_table(
        label: str,
        rows: Any,
        *,
        include_share: bool = False,
    ) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold", ratio=1)
        table.add_column("Count", justify="right", style=_CYAN)
        if include_share:
            table.add_column("Share", justify="right")
            table.add_column("Scale")
        for row in rows:
            values = [row.label, str(row.count)]
            if include_share:
                share = row.share or 0.0
                values.extend(
                    [
                        StatisticsPane._percent(share),
                        StatisticsPane._share_bar(share, 1.0),
                    ]
                )
            table.add_row(*values)
        return table

    @staticmethod
    def _activity_table(label: str, rows: Any) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold", ratio=1)
        table.add_column("Count", justify="right", style=_CYAN)
        table.add_column("Agents", justify="right")
        for row in rows:
            table.add_row(row.label, str(row.count), str(row.distinct_agents))
        return table

    @staticmethod
    def _distribution_table(label: str, rows: Any) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold")
        table.add_column("Count", justify="right", style=_CYAN)
        table.add_column("Scale", ratio=1)
        maximum = max((row.count for row in rows), default=0)
        for row in rows:
            table.add_row(
                row.label,
                str(row.count),
                StatisticsPane._share_bar(row.count, maximum),
            )
        return table

    def _paint_error(self, message: str) -> None:
        self._last_error = message
        self._update_heading()
        if self._last_result is not None:
            return
        self._set_tiles_visible(False)
        self._update_static(
            "#statistics-body",
            Panel(
                Align.center(Text(message, style="red"), vertical="middle"),
                title="Statistics unavailable",
                border_style="red",
                height=max(8, int(self.size.height or 24) - 10),
            ),
        )

    def _heading_text(self) -> Text:
        heading = Text()
        heading.append("Statistics", style=f"bold {_ACCENT}")
        heading.append("  ·  ")
        view_label = VIEW_LABELS[self._view]
        if self._view == "runtime":
            view_label += f" by {self._runtime_group_by.title()}"
        elif self._view == "projects":
            view_label += f" · {_PROJECTS_GROUP_LABELS[self._projects_group_by]}"
        heading.append(view_label, style="bold")
        heading.append(f"  ·  {self._range.label}", style=f"bold {_CYAN}")
        if self._project_filter is not None:
            heading.append(f"  ·  {self._project_filter}", style=f"bold {_GOLD}")
        if self._loading:
            heading.append("  ·  refreshing…", style="dim italic")
        elif self._last_error:
            heading.append("  ·  load failed", style="red")
        elif self._last_result is not None:
            updated = (
                datetime.fromtimestamp(self._last_result.generated_at)
                .astimezone()
                .strftime("%H:%M:%S")
            )
            heading.append(f"  ·  updated {updated}", style="dim")
        return heading

    def _hints_text(self) -> Text:
        bindings = statistics_help_bindings(self._keymaps)
        hints = Text(justify="center")
        if len(bindings) >= 2:
            hints.append(
                f"{bindings[0][0]} / {bindings[1][0]}", style=f"bold {_ACCENT}"
            )
            hints.append(" views")
        styles = (_CYAN, _GOLD, _GREEN, _ACCENT, _CYAN)
        for (key, description), color in zip(bindings[2:], styles, strict=False):
            if description == "Group By" and self._view == "runtime":
                description = f"Group: {self._runtime_group_by.title()}"
            elif description == "Group By" and self._view == "projects":
                description = (
                    f"Group: {_PROJECTS_GROUP_LABELS[self._projects_group_by]}"
                )
            hints.append("   ")
            hints.append(key, style=f"bold {color}")
            hints.append(f" {description.lower()}")
        return hints

    def _update_heading(self) -> None:
        self._update_static("#statistics-title", self._heading_text())

    def _update_hints(self) -> None:
        self._update_static("#statistics-hints", self._hints_text())

    def _set_tiles_visible(self, visible: bool) -> None:
        try:
            self.query_one("#statistics-tiles", Horizontal).display = visible
        except Exception:
            pass

    def _update_static(self, selector: str, content: Any) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _tile_width(self) -> int:
        width = max(60, int(self.size.width or 100))
        return max(12, (width - 4) // 5)

    @staticmethod
    def _percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    @staticmethod
    def _share_bar(value: float, maximum: float, *, width: int = 14) -> Text:
        ratio = min(1.0, max(0.0, float(value) / float(maximum))) if maximum else 0.0
        filled = round(ratio * width)
        text = Text()
        text.append("█" * filled, style=_ACCENT)
        text.append("░" * (width - filled), style="#444444")
        return text

    @staticmethod
    def _loading_panel(
        label: str,
        *,
        width: int = 18,
        height: int = 6,
    ) -> Panel:
        return Panel(
            Align.center(Text(label, style="dim italic"), vertical="middle"),
            border_style="#444444",
            width=width,
            height=height,
            padding=0,
        )


__all__ = ["StatisticsPane"]
