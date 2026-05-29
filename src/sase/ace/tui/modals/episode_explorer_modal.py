"""Episode Explorer modal for ACE."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import subprocess

from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.core.episode_wire import (
    EpisodeVerifyReportWire,
    EpisodeWire,
)
from sase.memory.episodes.inventory import (
    EpisodeInventoryItem,
    query_episode_inventory,
)
from sase.memory.episodes.verify import verify_episode

from ..actions.clipboard import copy_to_system_clipboard
from .base import FilterInput
from .episode_explorer_detail import EpisodeExplorerDetailMixin
from .episode_explorer_filters import (
    BANDS as _BANDS,
    RANGES as _RANGES,
    STATUSES as _STATUSES,
    VIEWS as _VIEWS,
    EpisodeExplorerDisplayRow as _EpisodeExplorerDisplayRow,
    EpisodeExplorerEdgeMode,
    EpisodeExplorerFilters as _EpisodeExplorerFilters,
    EpisodeExplorerLoadResult as _EpisodeExplorerLoadResult,
    EpisodeExplorerView,
    cycle_value as _cycle_value,
    display_rows as _display_rows,
    matches_filters as _matches_filters,
    replace_filters as _replace_filters,
)


_WORKER_GROUP = "episode-explorer"


class _EpisodeExplorerInput(FilterInput):
    """Filter input that keeps modal navigation available while focused."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Previous"),
        ("ctrl+r", "forward('cycle_range')", "Range"),
        ("ctrl+e", "forward('focus_inventory')", "Inventory"),
    ]

    def action_forward(self, action_name: str) -> None:
        modal = self.screen
        if isinstance(modal, EpisodeExplorerModal):
            getattr(modal, f"action_{action_name}")()


class EpisodeExplorerModal(EpisodeExplorerDetailMixin):
    """Browse project memory episodes without leaving ACE."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("q", "cancel", "Close"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("r", "cycle_range", "Range"),
        ("b", "cycle_band", "Band"),
        ("s", "cycle_status", "Status"),
        ("e", "toggle_edge_mode", "Edges"),
        ("1", "set_view('overview')", "Overview"),
        ("2", "set_view('timeline')", "Timeline"),
        ("3", "set_view('graph')", "Graph"),
        ("4", "set_view('sources')", "Sources"),
        ("5", "set_view('agent')", "Agent"),
        ("left", "prev_view", "Prev View"),
        ("right", "next_view", "Next View"),
        ("enter", "jump_to_canonical", "Canonical"),
        ("g", "jump_to_canonical", "Canonical"),
        ("y", "copy_episode_id", "Copy ID"),
        ("o", "open_source", "Open Source"),
        ("left_square_bracket", "prev_source", "Prev Source"),
        ("right_square_bracket", "next_source", "Next Source"),
        ("v", "verify_current", "Verify"),
        ("ctrl+r", "refresh_inventory", "Refresh"),
        ("ctrl+e", "focus_inventory", "Inventory"),
    ]

    def __init__(
        self,
        project: str,
        *,
        projects_root: Path | str | None = None,
        initial_items: list[EpisodeInventoryItem] | None = None,
        today: date | None = None,
        auto_load: bool = True,
    ) -> None:
        super().__init__()
        self._project = project
        self._projects_root = Path(projects_root) if projects_root is not None else None
        self._today = today or date.today()
        self._filters = _EpisodeExplorerFilters()
        self._items: list[EpisodeInventoryItem] = list(initial_items or [])
        self._visible_rows: list[_EpisodeExplorerDisplayRow] = []
        self._view: EpisodeExplorerView = "overview"
        self._edge_mode: EpisodeExplorerEdgeMode = "strong"
        self._episode_cache: dict[str, EpisodeWire] = {}
        self._verify_status: dict[str, str] = {}
        self._source_index: dict[str, int] = {}
        self._inventory_worker: Worker[_EpisodeExplorerLoadResult] | None = None
        self._verify_worker: Worker[EpisodeVerifyReportWire] | None = None
        self._loading = False
        self._loaded_once = initial_items is not None
        self._auto_load = auto_load
        self._error: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="episode-explorer-container"):
            yield Label(self._title_text(), id="episode-explorer-title")
            with Horizontal(id="episode-explorer-filter-row"):
                yield _EpisodeExplorerInput(
                    placeholder="Text filter",
                    id="episode-filter-query",
                )
                yield _EpisodeExplorerInput(
                    placeholder="Agent",
                    id="episode-filter-agent",
                )
                yield _EpisodeExplorerInput(
                    placeholder="ChangeSpec",
                    id="episode-filter-changespec",
                )
                yield _EpisodeExplorerInput(
                    placeholder="Bead",
                    id="episode-filter-bead",
                )
            yield Static("", id="episode-explorer-filter-summary")
            with Horizontal(id="episode-explorer-panels"):
                with Vertical(id="episode-explorer-left"):
                    yield OptionList(id="episode-explorer-list")
                with Vertical(id="episode-explorer-right"):
                    yield Static("", id="episode-explorer-tabs")
                    with VerticalScroll(id="episode-explorer-detail-scroll"):
                        yield Static("", id="episode-explorer-detail")
            yield Static("", id="episode-explorer-hints")

    def on_mount(self) -> None:
        self.query_one("#episode-filter-query", Input).focus()
        self._sync_filter_inputs()
        self._refresh_static_chrome()
        if self._items or not self._auto_load:
            self._apply_filters_from_cache()
        else:
            self.action_refresh_inventory()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != _WORKER_GROUP:
            return
        if worker is self._inventory_worker:
            self._handle_inventory_worker(event.state, worker)
            return
        if worker is self._verify_worker:
            self._handle_verify_worker(event.state, worker)

    def on_input_changed(self, event: Input.Changed) -> None:
        widget_id = str(event.input.id or "")
        if widget_id == "episode-filter-query":
            self._filters = _replace_filters(self._filters, query=event.value)
        elif widget_id == "episode-filter-agent":
            self._filters = _replace_filters(self._filters, agent=event.value)
        elif widget_id == "episode-filter-changespec":
            self._filters = _replace_filters(self._filters, changespec=event.value)
        elif widget_id == "episode-filter-bead":
            self._filters = _replace_filters(self._filters, bead=event.value)
        else:
            return
        self._apply_filters_from_cache()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != "episode-explorer-list":
            return
        self._render_selected_detail()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_inventory(self) -> None:
        self.query_one("#episode-explorer-list", OptionList).focus()

    def action_next_option(self) -> None:
        self.query_one("#episode-explorer-list", OptionList).action_cursor_down()

    def action_prev_option(self) -> None:
        self.query_one("#episode-explorer-list", OptionList).action_cursor_up()

    def action_refresh_inventory(self) -> None:
        if self._inventory_worker is not None and self._inventory_worker.is_running:
            self._inventory_worker.cancel()
        self._loading = True
        self._error = None
        self._refresh_static_chrome()
        self._render_loading()

        def task() -> _EpisodeExplorerLoadResult:
            try:
                items = query_episode_inventory(
                    self._project,
                    projects_root=self._projects_root,
                    order="time",
                )
            except Exception as exc:
                return _EpisodeExplorerLoadResult(
                    project=self._project,
                    items=[],
                    error=str(exc),
                )
            return _EpisodeExplorerLoadResult(project=self._project, items=items)

        self._inventory_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_WORKER_GROUP,
        )

    def action_cycle_range(self) -> None:
        self._filters = _replace_filters(
            self._filters,
            quick_range=_cycle_value(_RANGES, self._filters.quick_range),
        )
        self._apply_filters_from_cache()

    def action_cycle_band(self) -> None:
        self._filters = _replace_filters(
            self._filters,
            band=_cycle_value(_BANDS, self._filters.band),
        )
        self._apply_filters_from_cache()

    def action_cycle_status(self) -> None:
        self._filters = _replace_filters(
            self._filters,
            status=_cycle_value(_STATUSES, self._filters.status),
        )
        self._apply_filters_from_cache()

    def action_set_view(self, view: EpisodeExplorerView) -> None:
        if view not in _VIEWS:
            return
        self._view = view
        self._refresh_static_chrome()
        self._render_selected_detail()

    def action_prev_view(self) -> None:
        self.action_set_view(_cycle_value(_VIEWS, self._view, step=-1))

    def action_next_view(self) -> None:
        self.action_set_view(_cycle_value(_VIEWS, self._view))

    def action_toggle_edge_mode(self) -> None:
        self._edge_mode = "all" if self._edge_mode == "strong" else "strong"
        self._refresh_static_chrome()
        if self._view == "graph":
            self._render_selected_detail()

    def action_copy_episode_id(self) -> None:
        row = self._selected_row()
        if row is None:
            self.notify("No episode selected", severity="warning")
            return
        if copy_to_system_clipboard(row.display_episode_id):
            self.notify(f"Copied episode id: {row.display_episode_id}")
        else:
            self.notify("Failed to copy episode id", severity="error")

    def action_jump_to_canonical(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        if not row.is_alias:
            if row.item.aliases:
                self.notify(
                    f"Already on canonical id {row.canonical_episode_id} "
                    f"({len(row.item.aliases)} alias id(s))"
                )
            return
        self._filters = _replace_filters(self._filters, status="all")
        self._sync_filter_inputs()
        self._apply_filters_from_cache(select_episode_id=row.canonical_episode_id)
        self.notify(
            f"Selected canonical episode {row.canonical_episode_id} "
            f"for alias {row.display_episode_id}"
        )

    def action_prev_source(self) -> None:
        self._step_source(-1)

    def action_next_source(self) -> None:
        self._step_source(1)

    def action_open_source(self) -> None:
        source = self._current_source()
        if source is None:
            self.notify("Selected episode has no source path", severity="warning")
            return
        path = Path(source.path).expanduser()
        editor = os.environ.get("EDITOR") or "nvim"
        try:
            with self.app.suspend():
                subprocess.run([editor, str(path)], check=False)
        except SuspendNotSupported:
            try:
                subprocess.run([editor, str(path)], check=False)
            except OSError as exc:
                self.notify(f"Failed to open source: {exc}", severity="error")
                return
        except OSError as exc:
            self.notify(f"Failed to open source: {exc}", severity="error")
            return
        self.notify(f"Opened source: {path}")

    def action_verify_current(self) -> None:
        row = self._selected_row()
        if row is None:
            self.notify("No episode selected", severity="warning")
            return
        episode = self._load_episode_for_row(row)
        if episode is None:
            return
        if self._verify_worker is not None and self._verify_worker.is_running:
            self._verify_worker.cancel()

        def task() -> EpisodeVerifyReportWire:
            return verify_episode(episode)

        self._verify_status[episode.episode_id] = "checking"
        self._render_selected_detail()
        self._verify_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_WORKER_GROUP,
        )

    def _handle_inventory_worker(
        self,
        state: WorkerState,
        worker: Worker[_EpisodeExplorerLoadResult],
    ) -> None:
        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._loading = False
            if worker is self._inventory_worker:
                self._inventory_worker = None
        if state == WorkerState.SUCCESS:
            result = worker.result
            if result is None:
                self._error = "Episode inventory worker returned no result"
                self._items = []
                self._apply_filters_from_cache()
                return
            self._items = result.items
            self._loaded_once = True
            self._error = result.error
            self._episode_cache.clear()
            self._verify_status.clear()
            self._source_index.clear()
            self._apply_filters_from_cache()
            return
        if state == WorkerState.ERROR:
            self._error = "Failed to load episode inventory"
            self._items = []
            self._apply_filters_from_cache()

    def _handle_verify_worker(
        self,
        state: WorkerState,
        worker: Worker[EpisodeVerifyReportWire],
    ) -> None:
        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            if worker is self._verify_worker:
                self._verify_worker = None
        if state == WorkerState.SUCCESS:
            report = worker.result
            if report is None:
                self.notify("Episode verification returned no result", severity="error")
                return
            status = "ok" if report.ok else "drift"
            self._verify_status[report.episode_id] = (
                f"{status}: {report.ok_count} ok, "
                f"{report.missing_count} missing, {report.changed_count} changed"
            )
            self.notify(f"Episode verification: {status}")
            self._render_selected_detail()
        elif state == WorkerState.ERROR:
            row = self._selected_row()
            if row is not None:
                self._verify_status[row.canonical_episode_id] = "error"
            self.notify("Episode verification failed", severity="error")
            self._render_selected_detail()

    def _apply_filters_from_cache(
        self, *, select_episode_id: str | None = None
    ) -> None:
        previous = select_episode_id or self._selected_display_episode_id()
        filtered = [
            item
            for item in self._items
            if _matches_filters(item, self._filters, today=self._today)
        ]
        self._visible_rows = _display_rows(filtered, self._filters.status)
        self._refresh_static_chrome()
        self._refresh_options(previous)
        self._render_selected_detail()


__all__ = [
    "EpisodeExplorerModal",
]
