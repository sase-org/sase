"""Episode Explorer modal for ACE."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.core.episode_wire import (
    EpisodeSourceRefWire,
    EpisodeVerifyReportWire,
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.inventory import (
    EpisodeInventoryItem,
    query_episode_inventory,
)
from sase.memory.episodes.render import (
    render_agent_text,
    render_graph_text,
    render_overview_text,
    render_sources_text,
    render_timeline_text,
)
from sase.memory.episodes.storage import EPISODE_JSON_FILE_NAME
from sase.memory.episodes.verify import verify_episode

from ..actions.clipboard import copy_to_system_clipboard
from .base import FilterInput


EpisodeExplorerView = Literal["overview", "timeline", "graph", "sources", "agent"]
EpisodeExplorerRange = Literal["all", "today", "yesterday", "week", "month"]
EpisodeExplorerBand = Literal["all", "high", "medium", "low", "unknown"]
EpisodeExplorerStatus = Literal["all", "v2", "v1", "aliases"]
EpisodeExplorerEdgeMode = Literal["strong", "all"]

_RANGES: tuple[EpisodeExplorerRange, ...] = (
    "all",
    "today",
    "yesterday",
    "week",
    "month",
)
_BANDS: tuple[EpisodeExplorerBand, ...] = ("all", "high", "medium", "low", "unknown")
_STATUSES: tuple[EpisodeExplorerStatus, ...] = ("all", "v2", "v1", "aliases")
_VIEWS: tuple[EpisodeExplorerView, ...] = (
    "overview",
    "timeline",
    "graph",
    "sources",
    "agent",
)
_WORKER_GROUP = "episode-explorer"


@dataclass(frozen=True)
class _EpisodeExplorerFilters:
    """Current inventory filters."""

    quick_range: EpisodeExplorerRange = "week"
    query: str = ""
    band: EpisodeExplorerBand = "all"
    agent: str = ""
    changespec: str = ""
    bead: str = ""
    status: EpisodeExplorerStatus = "all"


@dataclass(frozen=True)
class _EpisodeExplorerDisplayRow:
    """One selectable row in the left inventory pane."""

    item: EpisodeInventoryItem
    display_episode_id: str
    canonical_episode_id: str
    is_alias: bool = False
    alias_reason: str = ""


@dataclass(frozen=True)
class _EpisodeExplorerLoadResult:
    """Background inventory load result."""

    project: str
    items: list[EpisodeInventoryItem]
    error: str | None = None


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


class EpisodeExplorerModal(ModalScreen[None]):
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

    def _refresh_options(self, previous_episode_id: str | None) -> None:
        option_list = self.query_one("#episode-explorer-list", OptionList)
        option_list.clear_options()
        for index, row in enumerate(self._visible_rows):
            option_list.add_option(Option(_row_text(row), id=f"episode-row-{index}"))
        if not self._visible_rows:
            option_list.highlighted = None
            return
        target_index = 0
        if previous_episode_id:
            for index, row in enumerate(self._visible_rows):
                if row.display_episode_id == previous_episode_id:
                    target_index = index
                    break
        option_list.highlighted = target_index

    def _render_selected_detail(self) -> None:
        detail = self.query_one("#episode-explorer-detail", Static)
        row = self._selected_row()
        if self._loading:
            detail.update("Loading episode inventory...")
            return
        if self._error:
            detail.update(f"Episode inventory error: {self._error}")
            return
        if row is None:
            if self._loaded_once:
                detail.update("No episodes match the current filters.")
            else:
                detail.update("Episode inventory has not loaded yet.")
            return
        episode = self._load_episode_for_row(row)
        if episode is None:
            return
        detail.update(self._detail_text(row, episode))
        try:
            self.query_one(
                "#episode-explorer-detail-scroll", VerticalScroll
            ).scroll_home(animate=False)
        except Exception:
            pass

    def _render_loading(self) -> None:
        self.query_one("#episode-explorer-detail", Static).update(
            "Loading episode inventory..."
        )

    def _detail_text(
        self,
        row: _EpisodeExplorerDisplayRow,
        episode: EpisodeWire,
    ) -> str:
        width = max(72, min(110, self.size.width - 42 if self.size.width else 88))
        verify_status = self._verify_status.get(episode.episode_id, "not checked")
        alias_line = (
            f"Alias: {row.display_episode_id} -> {row.canonical_episode_id}\n"
            if row.is_alias
            else ""
        )
        source_line = ""
        if self._view == "sources":
            current = self._current_source(episode=episode)
            if current is not None:
                source_line = f"Source cursor: {current.id} {current.path}\n"
        header = (
            f"View: {self._view}"
            f"{' (' + self._edge_mode + ')' if self._view == 'graph' else ''}\n"
            f"Verification: {verify_status}\n"
            f"{alias_line}"
            f"{source_line}\n"
        )
        if self._view == "overview":
            body = render_overview_text(episode, width=width)
        elif self._view == "timeline":
            body = render_timeline_text(episode, width=width)
        elif self._view == "graph":
            body = render_graph_text(episode, edge_mode=self._edge_mode, width=width)
        elif self._view == "sources":
            body = render_sources_text(episode, width=width)
        else:
            body = render_agent_text(episode, width=width)
        return header + body

    def _load_episode_for_row(
        self,
        row: _EpisodeExplorerDisplayRow,
    ) -> EpisodeWire | None:
        cached = self._episode_cache.get(row.canonical_episode_id)
        if cached is not None:
            return cached
        episode_path = (
            project_episodes_dir(self._project, projects_root=self._projects_root)
            / row.canonical_episode_id
            / EPISODE_JSON_FILE_NAME
        )
        try:
            payload = json.loads(episode_path.read_text(encoding="utf-8"))
            episode = episode_wire_from_dict(payload)
        except Exception as exc:
            self.query_one("#episode-explorer-detail", Static).update(
                f"Failed to read {episode_path}: {exc}"
            )
            return None
        self._episode_cache[row.canonical_episode_id] = episode
        return episode

    def _selected_row(self) -> _EpisodeExplorerDisplayRow | None:
        option_list = self.query_one("#episode-explorer-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        if highlighted < 0 or highlighted >= len(self._visible_rows):
            return None
        return self._visible_rows[highlighted]

    def _selected_display_episode_id(self) -> str | None:
        row = self._selected_row_or_none()
        return row.display_episode_id if row is not None else None

    def _selected_row_or_none(self) -> _EpisodeExplorerDisplayRow | None:
        try:
            return self._selected_row()
        except Exception:
            return None

    def _current_source(
        self,
        *,
        episode: EpisodeWire | None = None,
    ) -> EpisodeSourceRefWire | None:
        row = self._selected_row()
        if row is None:
            return None
        if episode is None:
            episode = self._load_episode_for_row(row)
        if episode is None:
            return None
        sources = [source for source in episode.sources if source.path]
        if not sources:
            return None
        index = self._source_index.get(episode.episode_id, 0) % len(sources)
        self._source_index[episode.episode_id] = index
        return sources[index]

    def _step_source(self, step: int) -> None:
        row = self._selected_row()
        if row is None:
            return
        episode = self._load_episode_for_row(row)
        if episode is None:
            return
        sources = [source for source in episode.sources if source.path]
        if not sources:
            return
        current = self._source_index.get(episode.episode_id, 0)
        self._source_index[episode.episode_id] = (current + step) % len(sources)
        if self._view != "sources":
            self._view = "sources"
            self._refresh_static_chrome()
        self._render_selected_detail()

    def _refresh_static_chrome(self) -> None:
        self.query_one("#episode-explorer-title", Label).update(self._title_text())
        self.query_one("#episode-explorer-filter-summary", Static).update(
            self._filter_summary()
        )
        self.query_one("#episode-explorer-tabs", Static).update(self._tabs_text())
        self.query_one("#episode-explorer-hints", Static).update(self._hints_text())

    def _sync_filter_inputs(self) -> None:
        values = {
            "episode-filter-query": self._filters.query,
            "episode-filter-agent": self._filters.agent,
            "episode-filter-changespec": self._filters.changespec,
            "episode-filter-bead": self._filters.bead,
        }
        for widget_id, value in values.items():
            try:
                input_widget = self.query_one(f"#{widget_id}", Input)
                if input_widget.value != value:
                    input_widget.value = value
            except Exception:
                pass

    def _title_text(self) -> str:
        status = "loading" if self._loading else f"{len(self._visible_rows)} shown"
        return f"Episode Explorer - {self._project} [{status}]"

    def _filter_summary(self) -> str:
        since, until = _range_bounds(self._filters.quick_range, today=self._today)
        range_text = str(self._filters.quick_range)
        if since or until:
            range_text += f" ({since or '-'}..{until or '-'})"
        parts = [
            f"range={range_text}",
            f"band={self._filters.band}",
            f"status={self._filters.status}",
            f"loaded={len(self._items)}",
        ]
        if self._filters.query.strip():
            parts.append(f"text={self._filters.query.strip()}")
        if self._filters.agent.strip():
            parts.append(f"agent={self._filters.agent.strip()}")
        if self._filters.changespec.strip():
            parts.append(f"changespec={self._filters.changespec.strip()}")
        if self._filters.bead.strip():
            parts.append(f"bead={self._filters.bead.strip()}")
        if self._error:
            parts.append("error")
        return "  ".join(parts)

    def _tabs_text(self) -> str:
        labels = []
        for index, view in enumerate(_VIEWS, 1):
            label = f"{index}:{view}"
            labels.append(f"[{label}]" if view == self._view else label)
        return "  ".join(labels)

    def _hints_text(self) -> str:
        return (
            "r range  b band  s status  1-5 views  e edges  "
            "o open source  y copy id  g canonical  v verify  "
            "^r refresh  ^e inventory"
        )


def _replace_filters(
    filters: _EpisodeExplorerFilters,
    **changes: Any,
) -> _EpisodeExplorerFilters:
    return replace(filters, **changes)


def _cycle_value[T: str](
    values: tuple[T, ...],
    current: T,
    *,
    step: int = 1,
) -> T:
    try:
        index = values.index(current)
    except ValueError:
        return values[0]
    return values[(index + step) % len(values)]


def _display_rows(
    items: list[EpisodeInventoryItem],
    status: EpisodeExplorerStatus,
) -> list[_EpisodeExplorerDisplayRow]:
    rows: list[_EpisodeExplorerDisplayRow] = []
    for item in items:
        if status != "aliases":
            rows.append(
                _EpisodeExplorerDisplayRow(
                    item=item,
                    display_episode_id=item.row.episode_id,
                    canonical_episode_id=item.row.episode_id,
                )
            )
        if status in {"all", "aliases"}:
            for alias in item.aliases:
                rows.append(
                    _EpisodeExplorerDisplayRow(
                        item=item,
                        display_episode_id=alias.alias_episode_id,
                        canonical_episode_id=alias.canonical_episode_id,
                        is_alias=True,
                        alias_reason=alias.reason,
                    )
                )
    return rows


def _matches_filters(
    item: EpisodeInventoryItem,
    filters: _EpisodeExplorerFilters,
    *,
    today: date,
) -> bool:
    if filters.band != "all" and item.row.importance_band.lower() != filters.band:
        return False
    if filters.status == "v1" and item.version != "v1":
        return False
    if filters.status == "v2" and item.version != "v2":
        return False
    if filters.status == "aliases" and not item.aliases:
        return False
    since, until = _range_bounds(filters.quick_range, today=today)
    if not _matches_date_window(item, since=since, until=until):
        return False
    if not _contains_all(_agent_haystack(item), filters.agent):
        return False
    if not _contains_all(item.row.changespec_name or "", filters.changespec):
        return False
    if not _contains_all(" ".join(item.row.bead_ids), filters.bead):
        return False
    return _contains_all(_query_haystack(item), filters.query)


def _range_bounds(
    quick_range: EpisodeExplorerRange,
    *,
    today: date,
) -> tuple[str | None, str | None]:
    if quick_range == "all":
        return None, None
    if quick_range == "today":
        text = today.isoformat()
        return text, text
    if quick_range == "yesterday":
        text = (today - timedelta(days=1)).isoformat()
        return text, text
    if quick_range == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    first = today.replace(day=1)
    return first.isoformat(), today.isoformat()


def _matches_date_window(
    item: EpisodeInventoryItem,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    if since is None and until is None:
        return True
    row = item.row
    start = row.first_event_at or row.last_event_at
    end = row.last_event_at or row.first_event_at
    if start is None or end is None:
        return False
    start_key = compact_timestamp(start)
    end_key = compact_timestamp(end)
    if since is not None and end_key < since.replace("-", "") + "000000":
        return False
    if until is not None and start_key > until.replace("-", "") + "235959":
        return False
    return True


def _contains_all(haystack: str, query: str) -> bool:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return True
    folded = haystack.casefold()
    return all(term in folded for term in terms)


def _agent_haystack(item: EpisodeInventoryItem) -> str:
    return " ".join(item.row.root_agent_names)


def _query_haystack(item: EpisodeInventoryItem) -> str:
    row = item.row
    return " ".join(
        [
            row.episode_id,
            row.title,
            row.summary_excerpt,
            row.component_key,
            row.status,
            row.importance_band,
            row.changespec_name or "",
            row.outcome or "",
            " ".join(row.root_agent_names),
            " ".join(row.bead_ids),
            " ".join(alias.alias_episode_id for alias in item.aliases),
            " ".join(item.warnings),
            item.version,
        ]
    )


def _row_text(row: _EpisodeExplorerDisplayRow) -> Text:
    text = Text(no_wrap=True)
    item = row.item
    if row.is_alias:
        text.append("alias ", style="bold #D7AF5F")
        text.append(_short(row.display_episode_id, 28), style="bold #87D7FF")
        text.append(" -> ", style="dim")
        text.append(_short(row.canonical_episode_id, 28), style="bold")
        if row.alias_reason:
            text.append(f"  {row.alias_reason}", style="dim")
        text.append("\n")
        text.append(f"  {_short(item.row.title, 76)}", style="dim")
        return text
    row_data = item.row
    text.append(_time_span(row_data.first_event_at, row_data.last_event_at))
    text.append(f"  {row_data.importance_band}", style="bold #D7AF5F")
    text.append(f"  {row_data.status}", style="dim")
    text.append(f"  {item.version}", style="dim #87D7FF")
    if item.warnings:
        text.append(f"  warnings={len(item.warnings)}", style="bold red")
    text.append("\n")
    text.append(f"  {_short(row_data.episode_id, 24)}", style="bold #87D7FF")
    text.append(f"  {_short(row_data.title, 58)}")
    details = _row_details(item)
    if details:
        text.append(f"\n  {_short(details, 86)}", style="dim")
    return text


def _row_details(item: EpisodeInventoryItem) -> str:
    row = item.row
    parts = []
    if row.root_agent_names:
        parts.append("agents=" + ",".join(row.root_agent_names))
    if row.changespec_name:
        parts.append(f"cl={row.changespec_name}")
    if row.bead_ids:
        parts.append("beads=" + ",".join(row.bead_ids))
    parts.append(f"sources={row.source_count}")
    if item.aliases:
        parts.append(f"aliases={len(item.aliases)}")
    return "  ".join(parts)


def _time_span(first: str | None, last: str | None) -> str:
    start = _format_timestamp(first)
    end = _format_timestamp(last)
    if start and end and start != end:
        return f"{start}..{end}"
    return start or end or "undated"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    compact = compact_timestamp(value)
    if len(compact) >= 12 and compact[:12].isdigit():
        return (
            f"{compact[:4]}-{compact[4:6]}-{compact[6:8]} "
            f"{compact[8:10]}:{compact[10:12]}"
        )
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return value


def _short(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


__all__ = [
    "EpisodeExplorerModal",
]
