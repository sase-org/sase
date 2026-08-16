"""Historical agent-activity statistics for the SASE Admin Center."""

from __future__ import annotations

from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, VerticalScroll
from textual.events import Click, Key, Resize
from textual.message import Message
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import (
    StatisticsPaneKeymaps,
    build_statistics_bindings,
    load_keymap_registry,
    split_key_alternatives,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip
from sase.stats.ranges import (
    DEFAULT_PRESET,
    PRESET_ORDER,
    PresetKey,
    StatsRange,
    parse_custom_range,
    resolve_preset,
)

from .statistics_pane_data import (
    PERF_GROUP_ORDER,
    PROJECTS_GROUP_ORDER,
    XPROMPTS_GROUP_ORDER,
    VIEW_COMPACT_LABELS,
    VIEW_LABELS,
    VIEW_MICRO_LABELS,
    VIEW_ORDER,
    PerfGroupBy,
    ProjectsGroupBy,
    StatisticsView,
    StatisticsViewData,
    XPromptsGroupBy,
    load_statistics_view,
    statistics_view_supports_grouping,
)
from .statistics_pane_rendering import StatisticsPanePresentationBase

_ACCENT = "#FF87D7"
_REFRESH_INTERVAL_SECONDS = 30.0
# Full eight-tab line is 119 cells; compact is 82. Keep a few cells of slack
# so 120- and 90-column Admin Center layouts never clip the strip.
_VIEWS_COMPACT_BELOW_WIDTH = 123
_VIEWS_MICRO_BELOW_WIDTH = 83
_VIEW_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(
        view,
        VIEW_LABELS[view],
        _ACCENT,
        compact_label=VIEW_COMPACT_LABELS[view],
        micro_label=VIEW_MICRO_LABELS[view],
    )
    for view in VIEW_ORDER
)
OVERVIEW_TILE_TARGETS: tuple[tuple[str, StatisticsView], ...] = (
    ("Agents Run", "projects"),
    ("Success Rate", "projects"),
    ("Commits", "projects"),
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

    def compose(self) -> ComposeResult:
        with Horizontal(id="statistics-heading"):
            yield Static(self._heading_text(), id="statistics-title", markup=False)
            yield Static(self._status_text(), id="statistics-status", markup=False)
        yield PanelTabStrip(
            _VIEW_TABS,
            self._view,
            show_numbers=True,
            uppercase_active=True,
            compact_below=_VIEWS_COMPACT_BELOW_WIDTH,
            compact_separator="│",
            micro_below=_VIEWS_MICRO_BELOW_WIDTH,
            micro_separator="│",
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
                classes=(
                    "statistics-scope-part"
                    if statistics_view_supports_grouping(self._view)
                    else "statistics-scope-part hidden"
                ),
                markup=False,
            )
            yield Static(
                self._project_scope_text(),
                id="statistics-scope-project",
                classes="statistics-scope-part",
                markup=False,
            )
            yield Static(
                self._xprompt_scope_text(),
                id="statistics-scope-xprompt",
                classes=(
                    "statistics-scope-part"
                    if self._view == "xprompts"
                    else "statistics-scope-part hidden"
                ),
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
        if not statistics_view_supports_grouping(self._view):
            return
        if self._view == "projects":
            index = PROJECTS_GROUP_ORDER.index(self._projects_group_by)
            self._projects_group_by = PROJECTS_GROUP_ORDER[
                (index + 1) % len(PROJECTS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)
        elif self._view == "xprompts":
            index = XPROMPTS_GROUP_ORDER.index(self._xprompts_group_by)
            self._xprompts_group_by = XPROMPTS_GROUP_ORDER[
                (index + 1) % len(XPROMPTS_GROUP_ORDER)
            ]
            self._selection_changed(reload=False)
        elif self._view == "perf":
            index = PERF_GROUP_ORDER.index(self._perf_group_by)
            self._perf_group_by = PERF_GROUP_ORDER[(index + 1) % len(PERF_GROUP_ORDER)]
            self._selection_changed(reload=True)

    def action_cycle_project_filter(self) -> None:
        """Cycle forward through All and cached ranked projects."""
        self._cycle_project_filter(1)

    def action_cycle_project_filter_reverse(self) -> None:
        """Cycle backward through All and cached ranked projects."""
        self._cycle_project_filter(-1)

    def action_focus_xprompt(self) -> None:
        """Open the cached xprompt picker while viewing loaded XPrompts data."""
        if self._view != "xprompts" or self._last_result is None:
            return
        from .statistics_xprompt_picker_modal import (
            StatisticsXPromptPickerModal,
            XPromptFocusChoice,
        )

        rows = self._last_result.views.xprompts.rows
        if self._xprompt_focus_options:
            by_name = {row.name: row for row in rows}
            rows = tuple(
                by_name[name] for name in self._xprompt_focus_options if name in by_name
            )

        def on_picked(choice: XPromptFocusChoice | None) -> None:
            if choice is None:
                return
            self._xprompt_focus = choice.name
            self._selection_changed(reload=True)
            self.focus()

        self.app.push_screen(
            StatisticsXPromptPickerModal(
                rows,
                current_focus=self._xprompt_focus,
            ),
            on_picked,
        )

    def action_clear_xprompt_focus(self) -> None:
        """Return to all xprompts when a focus is active."""
        if self._xprompt_focus is None:
            return
        self._xprompt_focus = None
        self._selection_changed(reload=True)

    def _cycle_project_filter(self, delta: int) -> None:
        """Cycle projects in ``delta`` direction or escape an empty filter."""
        if (
            self._project_filter is not None
            and self._last_result is not None
            and self._last_result.project_filter == self._project_filter
            and self._last_result.views.empty
        ):
            self._project_filter = None
            self._selection_changed(reload=True)
            return
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
                projects_group_by=self._projects_group_by,
                xprompts_group_by=self._xprompts_group_by,
                perf_group_by=self._perf_group_by,
                project_label=project_label,
                xprompt_focus_label=(
                    "All xprompts"
                    if self._xprompt_focus is None
                    else f"#{self._xprompt_focus}"
                ),
                generated_at=result.generated_at if result is not None else None,
                keymaps=self._keymaps,
            )
        )

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
        needs_perf = view == "perf" and (
            self._last_result is None or self._last_result.perf is None
        )
        self._selection_changed(reload=needs_perf)

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


__all__ = ["OVERVIEW_TILE_TARGETS", "StatisticsPane"]
