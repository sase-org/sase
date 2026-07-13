"""Async repository and workspace inventory panes for the Admin Center."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Protocol, cast

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.worker import Worker, WorkerState
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.repo_inventory import (
    RepoInventoryIssue,
    RepoRecord,
    collect_repo_inventory,
)
from sase.workspace_provider.inventory import (
    WorkspaceInventoryIssue,
    WorkspaceInventoryRecord,
    collect_workspace_inventory,
)

from .base import FilterInput, OptionListNavigationMixin
from .project_inventory_rendering import (
    repo_column_header_text,
    repo_detail_text,
    repo_hints_text,
    repo_record_label,
    repo_summary_text,
    workspace_column_header_text,
    workspace_detail_text,
    workspace_hints_text,
    workspace_record_label,
    workspace_summary_text,
)


class _InventoryIssue(Protocol):
    @property
    def project(self) -> str: ...

    @property
    def message(self) -> str: ...


@dataclass(frozen=True)
class _InventoryLoadResult[RecordT, IssueT: _InventoryIssue]:
    records: tuple[RecordT, ...]
    issues: tuple[IssueT, ...]
    loaded_at: float


class InventoryProjectFilterRequested(Message):
    """Request that the host open its shared project picker for *pane*."""

    def __init__(
        self,
        pane: RepoInventoryPane | WorkspaceInventoryPane,
    ) -> None:
        super().__init__()
        self.pane = pane


class _InventoryFilterInput(FilterInput):
    """Filter input that leaves pane sub-tab cycle keys available."""

    def on_key(self, event: events.Key) -> None:
        if event.key not in ("left_square_bracket", "right_square_bracket"):
            return
        node: object | None = self.parent
        while node is not None:
            if event.key == "left_square_bracket":
                action = getattr(node, "action_cycle_subtab_reverse", None)
            else:
                action = getattr(node, "action_cycle_subtab", None)
            if callable(action):
                event.stop()
                event.prevent_default()
                action()
                return
            node = getattr(node, "parent", None)


class _InventoryPaneBase[RecordT, IssueT: _InventoryIssue](
    OptionListNavigationMixin,
    Vertical,
):
    """Shared cached-list mechanics for the two read-only inventory panes."""

    _prefix: str
    _option_list_id: str
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS[2:],
        ("/", "focus_filter", "Filter"),
        ("p", "pick_project", "Pick Project"),
        ("R", "reload_inventory", "Reload"),
        Binding("escape", "clear_project_filter", "Clear Project", show=False),
    ]

    def __init__(
        self,
        *,
        projects_root: Path | None,
        project_records: Sequence[ProjectRecordWire],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._projects_root = projects_root
        self._project_states: dict[str, str] = {}
        self._project_names: dict[str, str] = {}
        self._records: list[RecordT] = []
        self._scoped_records: list[RecordT] = []
        self._filtered_records: list[RecordT] = []
        self._issues: list[IssueT] = []
        self._project_filter: str | None = None
        self._text_filter = ""
        self._loading = False
        self._reload_pending = False
        self._load_error = ""
        self._loaded_at = time.time()
        self._worker: Worker[Any] | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._syncing_options = False
        self.set_project_records(project_records, refresh=False)

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id=f"{self._prefix}-summary")
        yield _InventoryFilterInput(
            placeholder=f"Type to filter {self._prefix}…",
            id=f"{self._prefix}-filter",
        )
        list_box = Vertical(id=f"{self._prefix}-box")
        list_box.border_title = self._prefix.title()
        with list_box:
            yield Static(self._column_header_text(), id=f"{self._prefix}-columns")
            yield OptionList(id=self._option_list_id)
        detail_box = VerticalScroll(id=f"{self._prefix}-detail-scroll")
        detail_box.border_title = "Details"
        with detail_box:
            yield Static("", id=f"{self._prefix}-detail")
        yield Static(self._hints_text(), id=f"{self._prefix}-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()
        self._start_inventory_load()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "clear_project_filter":
            return bool(self._project_filter)
        return super().check_action(action, parameters)

    def set_project_records(
        self,
        records: Sequence[ProjectRecordWire],
        *,
        refresh: bool = True,
    ) -> None:
        """Refresh enabled/disabled metadata without touching cached rows."""

        self._project_states = {record.project_name: record.state for record in records}
        self._project_names = {
            record.project_name: effective_project_name(record) for record in records
        }
        if self._project_filter not in self._project_states:
            self._project_filter = None
        self._apply_filters()
        if refresh:
            self._refresh_options()

    @property
    def project_filter(self) -> str | None:
        return self._project_filter

    def set_project_filter(self, project_key: str | None) -> None:
        """Apply a cached project scope, admitting disabled projects explicitly."""

        self._project_filter = (
            project_key if project_key in self._project_states else None
        )
        self._apply_filters()
        self._refresh_options()

    def focus_default(self) -> None:
        try:
            self.query_one(f"#{self._option_list_id}", OptionList).focus()
        except Exception:
            pass

    def _start_inventory_load(self) -> None:
        if self._loading:
            self._reload_pending = True
            return
        self._loading = True
        self._load_error = ""
        self._update_summary()
        self._worker = self.run_worker(
            self._load_inventory,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            selected = self._selected_record_id()
            result = event.worker.result
            self._loading = False
            if isinstance(result, _InventoryLoadResult):
                self._records = list(result.records)
                self._issues = list(result.issues)
                self._loaded_at = result.loaded_at
                self._apply_filters()
                self._refresh_options(preferred_id=selected)
            else:
                self._load_error = "inventory returned no result"
                self._update_summary()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = (
                str(event.worker.error)
                if event.worker.error
                else "inventory load failed"
            )
            self._update_summary()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if (
            event.state
            in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            )
            and self._reload_pending
        ):
            self._reload_pending = False
            self.call_later(self._start_inventory_load)

    def _apply_filters(self) -> None:
        if self._project_filter is not None:
            scoped = [
                record
                for record in self._records
                if self._record_project_key(record) == self._project_filter
            ]
        else:
            scoped = [
                record for record in self._records if self._enabled_by_default(record)
            ]
        self._scoped_records = scoped
        needle = self._text_filter.casefold().strip()
        self._filtered_records = [
            record
            for record in scoped
            if not needle or needle in self._record_haystack(record).casefold()
        ]

    def _create_options(self) -> list[Option]:
        if not self._filtered_records:
            if self._loading and not self._records:
                message = f"Loading {self._prefix} inventory…"
            elif self._text_filter.strip():
                message = f"No {self._prefix} match the current search"
            elif self._project_filter:
                message = "No inventory rows for the selected project"
            else:
                message = f"No registered {self._prefix}"
            return [Option(Text(message, style="dim"), id="empty")]
        return [
            Option(self._record_label(record), id=self._record_id(record))
            for record in self._filtered_records
        ]

    def _refresh_options(self, *, preferred_id: str | None = None) -> None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        current = preferred_id or self._selected_record_id()
        self._syncing_options = True
        try:
            option_list.clear_options()
            for option in self._create_options():
                option_list.add_option(option)
            if self._filtered_records:
                index = 0
                if current is not None:
                    for candidate, record in enumerate(self._filtered_records):
                        if self._record_id(record) == current:
                            index = candidate
                            break
                option_list.highlighted = index
            else:
                option_list.highlighted = None
        finally:
            self._syncing_options = False
        self._update_summary()
        self._update_detail()
        self._update_hints()

    def _selected_record(self) -> RecordT | None:
        try:
            highlighted = self.query_one(
                f"#{self._option_list_id}", OptionList
            ).highlighted
        except Exception:
            return None
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted]

    def _selected_record_id(self) -> str | None:
        record = self._selected_record()
        return self._record_id(record) if record is not None else None

    def _project_label(self) -> str | None:
        if self._project_filter is None:
            return None
        return self._project_names.get(self._project_filter, self._project_filter)

    def _issues_for(self, record: RecordT | None) -> tuple[str, ...]:
        if record is None:
            return ()
        project = self._record_project(record)
        return tuple(
            issue.message for issue in self._issues if issue.project == project
        )

    def _update_summary(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-summary", Static).update(
                self._summary_text()
            )
        except Exception:
            pass

    def _update_detail(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-detail", Static).update(
                self._detail_text(self._selected_record())
            )
        except Exception:
            pass

    def _schedule_detail_update(self) -> None:
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    def _update_hints(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-hints", Static).update(self._hints_text())
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"{self._prefix}-filter":
            return
        self._text_filter = event.value
        self._apply_filters()
        self._refresh_options()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.focus_default()

    def on_option_list_option_highlighted(
        self,
        _event: OptionList.OptionHighlighted,
    ) -> None:
        if not self._syncing_options:
            self._schedule_detail_update()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape" and self._project_filter is not None:
            event.stop()
            event.prevent_default()
            self.action_clear_project_filter()

    def action_focus_filter(self) -> None:
        self.query_one(f"#{self._prefix}-filter", _InventoryFilterInput).focus()

    def action_pick_project(self) -> None:
        self.post_message(
            InventoryProjectFilterRequested(
                cast(RepoInventoryPane | WorkspaceInventoryPane, self)
            )
        )

    def action_reload_inventory(self) -> None:
        self._start_inventory_load()

    def action_clear_project_filter(self) -> None:
        if self._project_filter is not None:
            self.set_project_filter(None)

    def _load_inventory(self) -> _InventoryLoadResult[RecordT, IssueT]:
        raise NotImplementedError

    def _column_header_text(self) -> Text:
        raise NotImplementedError

    def _record_label(self, record: RecordT) -> Text:
        raise NotImplementedError

    def _summary_text(self) -> Text:
        raise NotImplementedError

    def _detail_text(self, record: RecordT | None) -> Text:
        raise NotImplementedError

    def _hints_text(self) -> str:
        raise NotImplementedError

    def _record_id(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_haystack(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_project(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_project_key(self, record: RecordT) -> str:
        raise NotImplementedError

    def _enabled_by_default(self, record: RecordT) -> bool:
        raise NotImplementedError


class RepoInventoryPane(_InventoryPaneBase[RepoRecord, RepoInventoryIssue]):
    """Cached repository inventory view."""

    _prefix = "repos"
    _option_list_id = "repos-list"

    def _load_inventory(
        self,
    ) -> _InventoryLoadResult[RepoRecord, RepoInventoryIssue]:
        inventory = collect_repo_inventory(
            self._projects_root,
            include_disabled=True,
        )
        return _InventoryLoadResult(
            inventory.records,
            inventory.issues,
            time.time(),
        )

    def _column_header_text(self) -> Text:
        return repo_column_header_text()

    def _record_label(self, record: RepoRecord) -> Text:
        return repo_record_label(record)

    def _summary_text(self) -> Text:
        return repo_summary_text(
            self._scoped_records,
            project=self._project_label(),
            text_filter=self._text_filter,
            issue_count=len(self._issues),
            loading=self._loading,
            error=self._load_error,
        )

    def _detail_text(self, record: RepoRecord | None) -> Text:
        return repo_detail_text(record, issues=self._issues_for(record))

    def _hints_text(self) -> str:
        return repo_hints_text(project_filtered=self._project_filter is not None)

    def _record_id(self, record: RepoRecord) -> str:
        return f"{record.project_key}:{record.kind}:{record.name}:{record.path}"

    def _record_haystack(self, record: RepoRecord) -> str:
        return " ".join(
            (
                record.name,
                record.kind,
                record.project,
                record.project_key,
                record.path,
                record.description or "",
                record.source,
                record.env_name or "",
                "cloned" if record.exists else "missing",
            )
        )

    def _record_project(self, record: RepoRecord) -> str:
        return record.project

    def _record_project_key(self, record: RepoRecord) -> str:
        return record.project_key

    def _enabled_by_default(self, record: RepoRecord) -> bool:
        # Home is intentionally represented only by linked repositories and is
        # absent from the true-project state map; it remains part of the default
        # all-enabled repository inventory.
        return self._project_states.get(record.project_key, "enabled") == "enabled"


class WorkspaceInventoryPane(
    _InventoryPaneBase[WorkspaceInventoryRecord, WorkspaceInventoryIssue]
):
    """Cached workspace inventory view."""

    _prefix = "workspaces"
    _option_list_id = "workspaces-list"

    def _load_inventory(
        self,
    ) -> _InventoryLoadResult[WorkspaceInventoryRecord, WorkspaceInventoryIssue]:
        inventory = collect_workspace_inventory(
            self._projects_root,
            include_disabled=True,
        )
        return _InventoryLoadResult(
            inventory.records,
            inventory.issues,
            time.time(),
        )

    def _column_header_text(self) -> Text:
        return workspace_column_header_text()

    def _record_label(self, record: WorkspaceInventoryRecord) -> Text:
        return workspace_record_label(record, now=self._loaded_at)

    def _summary_text(self) -> Text:
        return workspace_summary_text(
            self._scoped_records,
            project=self._project_label(),
            text_filter=self._text_filter,
            issue_count=len(self._issues),
            loading=self._loading,
            error=self._load_error,
        )

    def _detail_text(self, record: WorkspaceInventoryRecord | None) -> Text:
        return workspace_detail_text(
            record,
            now=self._loaded_at,
            issues=self._issues_for(record),
        )

    def _hints_text(self) -> str:
        return workspace_hints_text(project_filtered=self._project_filter is not None)

    def _record_id(self, record: WorkspaceInventoryRecord) -> str:
        return f"{record.project_key}:{record.workspace_num}:{record.checkout_dir}"

    def _record_haystack(self, record: WorkspaceInventoryRecord) -> str:
        return " ".join(
            (
                str(record.workspace_num),
                record.project,
                record.project_key,
                record.checkout_dir,
                record.role,
                record.materialization,
                record.claim_agent or "",
                record.claim_cl_name or "",
                "claimed" if record.claimed else "free",
                "pinned" if record.pinned else "",
                "stale" if record.stale else "",
                "missing" if not record.exists else "",
                "dead" if record.claim_pid_alive is False else "",
            )
        )

    def _record_project(self, record: WorkspaceInventoryRecord) -> str:
        return record.project

    def _record_project_key(self, record: WorkspaceInventoryRecord) -> str:
        return record.project_key

    def _enabled_by_default(self, record: WorkspaceInventoryRecord) -> bool:
        return record.project_state == "enabled"


__all__ = [
    "InventoryProjectFilterRequested",
    "RepoInventoryPane",
    "WorkspaceInventoryPane",
    "_InventoryLoadResult",
]
