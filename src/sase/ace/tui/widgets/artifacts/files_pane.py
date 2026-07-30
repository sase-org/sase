"""Index-backed list and lifecycle for the Artifacts Files pane."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from rich.console import RenderableType
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.keymaps import (
    KeymapRegistry,
    key_display_name,
    load_keymap_registry,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.core.artifact_file_types import ArtifactFile
from sase.core.time import local_now
from sase.project_display_names import ProjectRefDisplaySnapshot

from .entry_navigation import ArtifactEntryTarget
from .file_filter_bar import FileFilterBar
from .files_data import (
    FILES_FIRST_PAGE_LIMIT,
    FilesSnapshot,
    load_files_snapshot,
)
from .files_detail import (
    FileDetailCacheKey,
    FileDetailData,
    build_file_detail,
    load_file_detail,
)
from .files_filter_session import FilesFilterSessionMixin
from .files_filtering import filter_files_snapshot
from .files_list import build_file_options
from .files_navigation import FilesNavigationMixin, FilesOptionList
from .files_rendering import (
    build_files_hints,
    build_files_info,
    build_files_status,
)
from .lifecycle import ArtifactsPaneLifecycle


class ArtifactsFilesPane(
    FilesFilterSessionMixin,
    FilesNavigationMixin,
    ArtifactsPaneLifecycle,
    Vertical,
):
    """Browse date-grouped artifact files without blocking the event loop."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._project_ref_display = ProjectRefDisplaySnapshot()
        self._registry = load_keymap_registry({})
        self._snapshot: FilesSnapshot | None = None
        self._filtered_count: int | None = None
        self._loading = False
        self._loading_full = False
        self._reload_pending = False
        self._pending_force = False
        self._pending_full = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._worker_generation = -1
        self._worker_full = False
        self._load_generation = 0
        self._extension_generation = 0
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._detail_worker: Worker[Any] | None = None
        self._detail_worker_generation = -1
        self._detail_generation = 0
        self._detail_cache: dict[FileDetailCacheKey, FileDetailData] = {}
        self._detail_keys_by_id: dict[str, FileDetailCacheKey] = {}
        self._init_files_navigation()
        self._init_files_filter_session()

    def compose(self) -> ComposeResult:
        yield FileFilterBar(id="file-filter-bar")
        yield Static(
            self._scope_text(),
            id="files-info",
            classes="artifacts-pane-info",
        )
        with Horizontal(id="files-panels"):
            list_panel = Vertical(id="files-list-panel")
            list_panel.border_title = "Files"
            with list_panel:
                yield Static("No artifact files found.", id="files-empty")
                yield Static(self._status_text(), id="files-status")
                yield FilesOptionList(id="files-list")
            detail_panel = Vertical(id="files-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="files-detail-scroll"):
                    yield Static("", id="files-detail")
        yield Static(self._hints_text(), id="files-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()

    def on_unmount(self) -> None:
        self._extension_generation += 1
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        cancel_pump_free_tasks(self)
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()
        if self._detail_worker is not None and not self._detail_worker.is_finished:
            self._detail_worker.cancel()

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False, full=False)

    def on_activate(self) -> None:
        self.focus_list()
        if not self._loading and (
            self._snapshot is None or self._snapshot.project != self.project_scope
        ):
            self._request_load(force=False, full=False)

    def on_refresh(self) -> None:
        self._request_load(force=True, full=False)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active registry for pane-scoped key hints."""

        self._registry = registry
        self._update_static("#files-info", self._scope_text())
        self._update_static("#files-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope and lazily replace stale rows."""

        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#files-info", self._scope_text())
        if not changed:
            return
        self._load_generation += 1
        self._extension_generation += 1
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False, full=False)
        else:
            self._refresh_options()

    def set_project_ref_display(
        self,
        project_ref_display: ProjectRefDisplaySnapshot,
    ) -> None:
        """Adopt the already-loaded project label projection."""

        preferred = self.selected_entry_target()
        self._project_ref_display = project_ref_display
        self._refresh_options(preferred_target=preferred)

    @property
    def snapshot(self) -> FilesSnapshot | None:
        return self._snapshot

    @property
    def selected_entry(self) -> ArtifactFile | None:
        row = self.selected_row()
        return None if row is None else row.entry

    def _request_load(self, *, force: bool, full: bool) -> None:
        """Coalesce one off-thread load with last-request-wins semantics."""

        if self._loading:
            self._reload_pending = True
            self._pending_force = self._pending_force or force
            self._pending_full = self._pending_full or full
            return

        project = self.project_scope
        generation = self._load_generation
        requested_limit = None if full else FILES_FIRST_PAGE_LIMIT
        self._loading = True
        self._loading_full = full
        self._load_error = None
        if self._snapshot is None or self._snapshot.project != project:
            self._refresh_options()
        else:
            self._update_status()

        def task() -> FilesSnapshot:
            return load_files_snapshot(project, requested_limit)

        worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )
        self._worker = worker
        self._worker_generation = generation
        self._worker_full = full

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._detail_worker:
            self._on_detail_worker_changed(event)
            return
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        full_request = self._worker_full
        generation = self._worker_generation
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            self._loading_full = False
            result = event.worker.result
            if (
                isinstance(result, FilesSnapshot)
                and generation == self._load_generation
                and result.project == self.project_scope
            ):
                preferred = self.selected_entry_target()
                cancel_jump = getattr(
                    self.app,
                    "_cancel_artifacts_jump_mode_for_model_change",
                    None,
                )
                if callable(cancel_jump):
                    cancel_jump("files")
                self._snapshot = result
                self._load_error = result.load_error
                self._detail_generation += 1
                if (
                    self._detail_worker is not None
                    and not self._detail_worker.is_finished
                ):
                    self._detail_worker.cancel()
                self._detail_cache.clear()
                self._detail_keys_by_id.clear()
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options(preferred_target=preferred)
                if (
                    not full_request
                    and not result.complete
                    and result.load_error is None
                ):
                    self._schedule_full_extension(generation)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loading_full = False
            self._load_error = str(event.worker.error or "Artifact files load failed")
            self._update_status()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False
            self._loading_full = False

        if terminal and self._reload_pending:
            force = self._pending_force
            full = self._pending_full
            self._reload_pending = False
            self._pending_force = False
            self._pending_full = False
            self.call_later(lambda: self._request_load(force=force, full=full))

    @on(OptionList.OptionHighlighted, "#files-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        self._update_static("#files-hints", self._hints_text())
        self._schedule_detail()

    @on(OptionList.OptionSelected, "#files-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast(Any, self.app).action_files_view_selected()

    def _schedule_full_extension(self, generation: int) -> None:
        """Yield first paint, then request the unbounded index extension."""

        self._extension_generation += 1
        extension_generation = self._extension_generation

        async def extend() -> None:
            await asyncio.sleep(0)
            if (
                extension_generation != self._extension_generation
                or generation != self._load_generation
                or not self.artifacts_active
            ):
                return
            self._request_load(force=False, full=True)

        spawn_pump_free_task(
            self,
            extend(),
            name="sase-artifacts-files-full-extension",
            registry_attr="_files_extension_tasks",
        )

    def _refresh_options(
        self,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        if preferred_target is None:
            preferred_target = self.selected_entry_target()
        values = self._display_filter_values()
        filtered = filter_files_snapshot(
            self._snapshot,
            values,
            self._project_ref_display,
        )
        self._filtered_count = None if filtered is None else len(filtered.rows)
        options, rows = build_file_options(
            filtered,
            project_scope=self.project_scope,
            project_ref_display=self._project_ref_display,
            loading=self._loading,
            now=local_now(),
            jump_hints=self._entry_jump_hints,
            marks=self._entry_marks,
        )
        self._set_file_rows(rows)
        highlighted = self._option_index_for_target(preferred_target)
        if highlighted is None:
            highlighted = next(
                (index for index, option in enumerate(options) if not option.disabled),
                None,
            )
        self._syncing_options = True
        try:
            option_list.replace_options(options, highlighted=highlighted)
        finally:
            self._syncing_options = False
        self._update_empty()
        self._update_status()
        self._update_static("#files-info", self._scope_text())
        self._update_static("#files-hints", self._hints_text())
        self._schedule_detail()

    def _update_empty(self) -> None:
        if not self.is_mounted:
            return
        empty = self.query_one("#files-empty", Static)
        option_list = self.query_one("#files-list", FilesOptionList)
        has_current_snapshot = (
            self._snapshot is not None and self._snapshot.project == self.project_scope
        )
        show_empty = (
            has_current_snapshot
            and not self._rows
            and not self._loading
            and self._load_error is None
        )
        if show_empty:
            values = self._display_filter_values()
            empty.update(
                "No artifact files found."
                if values.is_empty
                else "No artifact files match the active filters. "
                f"Press {key_display_name(self._registry.app.files_filters)} "
                "to edit or clear them."
            )
        empty.display = show_empty
        option_list.display = not show_empty

    def _update_status(self) -> None:
        self._update_static("#files-status", self._status_text())

    def _update_static(self, selector: str, content: RenderableType) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)

    def _scope_text(self) -> RenderableType:
        snapshot = (
            self._snapshot
            if self._snapshot is not None
            and self._snapshot.project == self.project_scope
            else None
        )
        return build_files_info(
            self._registry,
            snapshot,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filters=self._display_filter_values(),
            filtered_count=self._filtered_count,
        )

    def _status_text(self) -> RenderableType:
        snapshot = (
            self._snapshot
            if self._snapshot is not None
            and self._snapshot.project == self.project_scope
            else None
        )
        return build_files_status(
            snapshot,
            loading=self._loading,
            load_error=self._load_error,
            extending=self._loading_full,
        )

    def _hints_text(self) -> RenderableType:
        entry = self.selected_entry
        return build_files_hints(
            self._registry,
            has_agent=bool(entry is not None and entry.agent_name),
        )

    def _schedule_detail(self) -> None:
        self._render_detail(loading=True)
        entry = self.selected_entry
        if entry is None or self._detail_for(entry) is not None:
            self._render_detail(loading=False)
            return
        if self._detail_debouncer is None:
            self._request_detail()
        else:
            self._detail_debouncer.schedule(self._request_detail)

    def _request_detail(self) -> None:
        entry = self.selected_entry
        if entry is None or self._detail_for(entry) is not None:
            self._render_detail(loading=False)
            return
        view_mode = self._view_mode_for(entry)

        def task() -> FileDetailData:
            return load_file_detail(entry, view_mode=view_mode)

        self._detail_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-files-detail",
            exclusive=True,
            exit_on_error=False,
        )
        self._detail_worker_generation = self._detail_generation

    def _on_detail_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if (
                isinstance(result, FileDetailData)
                and self._detail_worker_generation == self._detail_generation
            ):
                self._detail_cache[result.cache_key] = result
                self._detail_keys_by_id[result.file_id] = result.cache_key
                entry = self.selected_entry
                if entry is not None and entry.id == result.file_id:
                    self._render_detail(loading=False)
        elif event.state == WorkerState.ERROR:
            self._render_detail(loading=False)

    def _detail_for(self, entry: ArtifactFile) -> FileDetailData | None:
        key = self._detail_keys_by_id.get(entry.id)
        return None if key is None else self._detail_cache.get(key)

    def _view_mode_for(self, entry: ArtifactFile) -> ArtifactViewMode:
        snapshot = self._snapshot
        return "text" if snapshot is None else snapshot.view_mode_for(entry)

    def _render_detail(self, *, loading: bool) -> None:
        if not self.is_mounted:
            return
        entry = self.selected_entry
        detail = None if entry is None else self._detail_for(entry)
        self.query_one("#files-detail", Static).update(
            build_file_detail(
                entry,
                detail,
                view_mode=None if entry is None else self._view_mode_for(entry),
                projects=self._project_ref_display,
                loading=loading and detail is None,
            )
        )

    def _set_filter_completion_sources(self) -> None:
        rows = () if self._snapshot is None else self._snapshot.rows
        self.query_one(FileFilterBar).set_completion_sources(
            projects=(
                self._project_ref_display.label_for_ref(row.project) or row.project
                for row in rows
                if row.project
            ),
            agents=(row.agent_name for row in rows if row.agent_name),
            workflows=(row.workflow for row in rows if row.workflow),
        )


__all__ = ["ArtifactsFilesPane"]
