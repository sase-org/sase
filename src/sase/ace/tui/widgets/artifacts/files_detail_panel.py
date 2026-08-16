"""Debounced detail-panel loading and rendering for the Files pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.artifact_file_types import ArtifactFile
from sase.project_display_names import ProjectRefDisplaySnapshot

from .files_data import FileVersion, FilesSnapshot, LogicalFile
from .files_detail import (
    FileDetailCacheKey,
    FileDetailData,
    build_file_detail,
    load_file_detail,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FilesDetailMixin(_MixinBase):
    """Own the detail worker, its cache, and the rendered detail panel."""

    _project_ref_display: ProjectRefDisplaySnapshot
    _snapshot: FilesSnapshot | None
    _detail_debouncer: DetailPanelDebouncer | None
    _detail_worker: Worker[Any] | None
    _detail_worker_generation: int
    _detail_generation: int
    _detail_cache: dict[FileDetailCacheKey, FileDetailData]
    _detail_keys_by_id: dict[str, FileDetailCacheKey]

    if TYPE_CHECKING:

        @property
        def selected_entry(self) -> ArtifactFile | None: ...

        @property
        def selected_logical_file(self) -> LogicalFile | None: ...

        @property
        def selected_version(self) -> FileVersion | None: ...

        def selected_version_index(self, logical: LogicalFile | None = None) -> int: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

    def _init_files_detail(self) -> None:
        self._detail_debouncer = None
        self._detail_worker = None
        self._detail_worker_generation = -1
        self._detail_generation = 0
        self._detail_cache = {}
        self._detail_keys_by_id = {}

    def _start_detail_debouncer(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)

    def _cancel_detail_debouncer(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def _cancel_detail_worker(self) -> None:
        if self._detail_worker is not None and not self._detail_worker.is_finished:
            self._detail_worker.cancel()

    def _invalidate_detail_cache(self) -> None:
        """Drop every cached detail and retire any in-flight load."""

        self._detail_generation += 1
        self._cancel_detail_worker()
        self._detail_cache.clear()
        self._detail_keys_by_id.clear()

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
        version = self.selected_version
        if snapshot is None or version is None:
            return "text"
        selected = self.selected_entry
        if selected is not None and selected.id == entry.id:
            return snapshot.view_mode_for(version)
        return "text"

    def _render_detail(self, *, loading: bool) -> None:
        if not self.is_mounted:
            return
        entry = self.selected_entry
        logical = self.selected_logical_file
        version = self.selected_version
        detail = None if entry is None else self._detail_for(entry)
        self.query_one("#files-detail", Static).update(
            build_file_detail(
                entry,
                detail,
                view_mode=None if entry is None else self._view_mode_for(entry),
                projects=self._project_ref_display,
                logical=logical,
                version=version,
                version_index=self.selected_version_index(logical),
                loading=loading and detail is None,
            )
        )
        self.refresh_relation_panel()


__all__ = ["FilesDetailMixin"]
