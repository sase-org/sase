"""Index-backed list and lifecycle for the Artifacts Files pane."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, cast

from rich.console import RenderableType
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.query_profile import compiled_profile_for_builtin_pane
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
from sase.core.time import local_now
from sase.core.artifact_file_types import ArtifactFile
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)
from sase.project_display_names import ProjectRefDisplaySnapshot

from .entry_navigation import ArtifactEntryTarget
from .file_filter_bar import FileFilterBar
from .files_data import (
    FILES_FIRST_PAGE_LIMIT,
    FileVersion,
    FilesSnapshot,
    LogicalFile,
    load_files_snapshot,
    selected_file_version_to_artifact_file,
)
from .files_detail import (
    FileDetailCacheKey,
    FileDetailData,
    build_file_detail,
    load_file_detail,
)
from .files_filter_session import FilesFilterSessionMixin
from .files_filtering import to_query_string
from .files_list import build_file_options, file_row_target
from .files_navigation import FilesNavigationMixin, FilesOptionList
from .files_rendering import (
    build_files_hints,
    build_files_info,
    build_files_status,
)
from ..._artifact_tab_model import ArtifactsPaneContract
from .query_rows import build_files_query_index
from .query_session import ArtifactQuerySession
from .shell import build_empty_card
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest
from .types import ARTIFACTS_ACCENTS


@dataclass(frozen=True, slots=True)
class _FilesSnapshotResult:
    snapshot: FilesSnapshot
    query_index: ArtifactQueryIndex
    initial_query_result: ArtifactQueryResult | None


@dataclass(frozen=True, slots=True)
class _FilesQueryIndexResult:
    generation: int
    display_generation: int
    query_index: ArtifactQueryIndex


class ArtifactsFilesPane(
    FilesFilterSessionMixin,
    FilesNavigationMixin,
    ArtifactsSnapshotPane,
):
    """Browse date-grouped artifact files without blocking the event loop."""

    can_focus = False

    def __init__(
        self,
        *,
        contract: ArtifactsPaneContract | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_snapshot_lifecycle()
        self.contract = contract
        profile = (
            contract.query_profile
            if contract is not None
            else compiled_profile_for_builtin_pane("files")
        )
        assert profile is not None
        self._query_profile = profile
        self._query_index: ArtifactQueryIndex | None = None
        self._query_session = ArtifactQuerySession(
            self,
            group="artifacts-files-query",
            on_current_result=lambda _result: self._refresh_options(
                preferred_target=self.selected_entry_target()
            ),
        )
        self._query_index_worker: Worker[Any] | None = None
        self._project_ref_display_generation = 0
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._project_ref_display = ProjectRefDisplaySnapshot()
        self._registry = load_keymap_registry({})
        self._filtered_count: int | None = None
        self._extension_generation = 0
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._detail_worker: Worker[Any] | None = None
        self._detail_worker_generation = -1
        self._detail_generation = 0
        self._detail_cache: dict[FileDetailCacheKey, FileDetailData] = {}
        self._detail_keys_by_id: dict[str, FileDetailCacheKey] = {}
        self._selected_version_indices: dict[str, int] = {}
        self._init_files_navigation()
        self._init_files_filter_session()

    def compose(self) -> ComposeResult:
        yield FileFilterBar(id="file-filter-bar", profile=self._query_profile)
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
        self._query_session.clear()
        if (
            self._query_index_worker is not None
            and not self._query_index_worker.is_finished
        ):
            self._query_index_worker.cancel()
        self._cancel_snapshot_worker()
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
        self.clear_pending_entry_target()
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
        self._project_ref_display_generation += 1
        self._request_query_index_rebuild()
        self._refresh_options(preferred_target=preferred)

    @property
    def snapshot(self) -> FilesSnapshot | None:
        return self._snapshot

    @property
    def selected_logical_file(self) -> LogicalFile | None:
        row = self.selected_row()
        return None if row is None else row.entry

    @property
    def selected_version(self) -> FileVersion | None:
        logical = self.selected_logical_file
        if logical is None:
            return None
        return logical.versions[self.selected_version_index(logical)]

    @property
    def selected_entry(self) -> ArtifactFile | None:
        version = self.selected_version
        return (
            None if version is None else selected_file_version_to_artifact_file(version)
        )

    @property
    def selected_view_mode(self) -> ArtifactViewMode | None:
        """Return the selected row's cached terminal-viewer classification."""

        entry = self.selected_version
        snapshot = self._current_snapshot()
        if entry is None or snapshot is None:
            return None
        return snapshot.view_mode_for(entry)

    def entries_for_targets(
        self,
        targets: Iterable[ArtifactEntryTarget],
    ) -> tuple[ArtifactFile, ...]:
        """Resolve visible stable targets to rows while preserving caller order."""

        entries = {file_row_target(row): row.entry for row in self._rows.values()}
        result = []
        for target in targets:
            logical = entries.get(target)
            if logical is None:
                continue
            result.append(
                selected_file_version_to_artifact_file(
                    logical.versions[self.selected_version_index(logical)]
                )
            )
        return tuple(result)

    def selected_version_index(self, logical: LogicalFile | None = None) -> int:
        logical = logical or self.selected_logical_file
        if logical is None:
            return 0
        index = self._selected_version_indices.get(
            logical.logical_id,
            len(logical.versions) - 1,
        )
        return max(0, min(index, len(logical.versions) - 1))

    def select_version(self, step: int) -> bool:
        logical = self.selected_logical_file
        if logical is None or len(logical.versions) <= 1:
            return False
        before = self.selected_version_index(logical)
        after = (before + step) % len(logical.versions)
        self._selected_version_indices[logical.logical_id] = after
        self._detail_generation += 1
        self._schedule_detail()
        self._refresh_options(preferred_target=self.selected_entry_target())
        return after != before

    def _request_load(self, *, force: bool, full: bool) -> None:
        """Coalesce one off-thread load with last-request-wins semantics."""

        self._request_snapshot(force=force, full=full)

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        if self._snapshot is None or self._snapshot.project != request.project:
            self._refresh_options()
        else:
            self._update_status()

    def _build_snapshot(self, request: SnapshotRequest) -> _FilesSnapshotResult:
        snapshot = load_files_snapshot(
            request.project,
            None if request.full else FILES_FIRST_PAGE_LIMIT,
        )
        query_index = build_files_query_index(
            snapshot,
            pane_id=self._query_profile.pane_id,
            generation=request.generation,
            profile=self._query_profile,
            project_ref_display=self._project_ref_display,
        )
        initial_query = to_query_string(self.filters)
        initial_result = (
            None
            if not initial_query
            else evaluate_artifact_query_many(initial_query, query_index)
        )
        return _FilesSnapshotResult(
            snapshot=snapshot,
            query_index=query_index,
            initial_query_result=initial_result,
        )

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return (
            isinstance(result, _FilesSnapshotResult)
            and request.generation == self._load_generation
            and result.snapshot.project == self.project_scope
            and result.query_index.generation == request.generation
        )

    def _apply_snapshot(self, result: Any, request: SnapshotRequest) -> None:
        preferred = self.selected_entry_target()
        cancel_jump = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel_jump):
            cancel_jump("files")
        self._query_session.clear()
        self._snapshot = result.snapshot
        self._query_index = result.query_index
        if result.initial_query_result is not None:
            self._query_session.remember(result.initial_query_result)
        self._load_error = result.snapshot.load_error
        self._detail_generation += 1
        if self._detail_worker is not None and not self._detail_worker.is_finished:
            self._detail_worker.cancel()
        self._detail_cache.clear()
        self._detail_keys_by_id.clear()
        self._selected_version_indices = {
            row.logical_id: min(
                self._selected_version_indices.get(
                    row.logical_id,
                    len(row.versions) - 1,
                ),
                len(row.versions) - 1,
            )
            for row in result.snapshot.rows
        }
        if self._filter_session_open:
            self._set_filter_completion_sources()
        self._refresh_options(preferred_target=preferred)
        if (
            not request.full
            and not result.snapshot.complete
            and result.snapshot.load_error is None
        ):
            self._schedule_full_extension(request.generation)

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error
        self._update_status()

    def _handle_auxiliary_worker(self, event: Worker.StateChanged) -> bool:
        if event.worker is self._query_index_worker:
            self._on_query_index_worker_changed(event)
            return True
        if self._query_session.handle_worker_state_changed(event):
            return True
        if event.worker is self._detail_worker:
            self._on_detail_worker_changed(event)
            return True
        return False

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
        pending_target = self._pending_entry_target
        if pending_target is not None:
            # A deferred cross-pane request wins over "keep the current
            # selection" — the caller landed here specifically to resolve it.
            preferred_target = pending_target
        elif preferred_target is None:
            preferred_target = self.selected_entry_target()
        values = self._display_filter_values()
        filtered, exact, pending = self._filtered_snapshot(values)
        if pending:
            if self._filter_session_open and self._filter_query_error is None:
                self.query_one(FileFilterBar).set_status(
                    None,
                    exact=False,
                    error=None,
                )
            return
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
        self._set_file_rows(rows, options)
        # Resolve the target against the freshly built ``options`` list
        # directly rather than the live OptionList, which still reflects
        # the pre-rebuild rows until ``replace_options`` runs below.
        preferred_option_id = (
            None
            if preferred_target is None
            else self._option_id_by_target.get(preferred_target)
        )
        highlighted = next(
            (
                index
                for index, option in enumerate(options)
                if option.id == preferred_option_id
            ),
            None,
        )
        if pending_target is not None:
            if highlighted is not None:
                self._pending_entry_target = None
            elif self._current_snapshot() is not None:
                self._pending_entry_target = None
                notify = getattr(self, "notify", None)
                if callable(notify):
                    notify(
                        "Linked file is no longer visible in Files",
                        severity="warning",
                    )
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
        if self._filter_session_open and self._filter_query_error is None:
            self.query_one(FileFilterBar).set_status(
                self._filtered_count,
                exact=exact,
                error=None,
            )
        self._schedule_detail()

    def _filtered_snapshot(
        self, values: Any
    ) -> tuple[FilesSnapshot | None, bool, bool]:
        snapshot = self._current_snapshot()
        if snapshot is None or values.is_empty:
            return snapshot, True, False
        query_index = self._query_index
        query = to_query_string(values)
        if query_index is None or not query:
            return snapshot, False, True
        result = self._query_session.result(query, query_index)
        if result is None:
            return snapshot, False, True
        matched = frozenset(result.matched_row_ids)
        return (
            replace(
                snapshot,
                rows=tuple(
                    row for row in snapshot.rows if f"file:{row.logical_id}" in matched
                ),
            ),
            True,
            False,
        )

    def _request_query_index_rebuild(self) -> None:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return
        worker = self._query_index_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        generation = self._load_generation
        display_generation = self._project_ref_display_generation
        display = self._project_ref_display

        def task() -> _FilesQueryIndexResult:
            return _FilesQueryIndexResult(
                generation=generation,
                display_generation=display_generation,
                query_index=build_files_query_index(
                    snapshot,
                    pane_id=self._query_profile.pane_id,
                    generation=generation,
                    profile=self._query_profile,
                    project_ref_display=display,
                ),
            )

        self._query_index = None
        self._query_session.clear()
        self._query_index_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-files-query-index",
            exclusive=True,
            exit_on_error=False,
        )

    def _on_query_index_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        self._query_index_worker = None
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, _FilesQueryIndexResult):
            return
        if (
            result.generation != self._load_generation
            or result.display_generation != self._project_ref_display_generation
        ):
            return
        self._query_index = result.query_index
        self._refresh_options(preferred_target=self.selected_entry_target())

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
            has_active_filter = not values.is_empty
            if self.contract is not None:
                empty.update(
                    build_empty_card(
                        self.contract,
                        has_active_filter=has_active_filter,
                        clear_filter_hint=(
                            f"Press {key_display_name(self._registry.app.files_filters)} "
                            "to edit or clear it."
                        ),
                    )
                )
            else:
                empty.update(
                    "No artifact files found."
                    if not has_active_filter
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

    def _accent(self) -> str:
        contract = self.contract
        return ARTIFACTS_ACCENTS["files"] if contract is None else contract.accent

    def _scope_text(self) -> RenderableType:
        snapshot = self._current_snapshot()
        return build_files_info(
            self._registry,
            snapshot,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filters=self._display_filter_values(),
            filtered_count=self._filtered_count,
            accent=self._accent(),
        )

    def _status_text(self) -> RenderableType:
        snapshot = self._current_snapshot()
        return build_files_status(
            snapshot,
            loading=self._loading,
            load_error=self._load_error,
            extending=self._loading_full,
        )

    def _current_snapshot(self) -> FilesSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None or snapshot.project != self.project_scope:
            return None
        return snapshot

    def _snapshot_matches_scope(self) -> bool:
        return self._current_snapshot() is not None

    def _snapshot_row_count(self) -> int:
        snapshot = self._current_snapshot()
        return 0 if snapshot is None else len(snapshot.rows)

    def _hints_text(self) -> RenderableType:
        entry = self.selected_entry
        return build_files_hints(
            self._registry,
            has_agent=bool(entry is not None and entry.agent_name),
            accent=self._accent(),
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

    def _set_filter_completion_sources(self) -> None:
        if self._query_index is None:
            self.query_one(FileFilterBar).set_completion_sources(
                projects=(), agents=(), workflows=()
            )
            return
        self.query_one(FileFilterBar).set_observed_facets(
            {
                key: values
                for key, values in self._query_index.facets.items()
                if key not in {"since", "until"}
            }
        )


__all__ = ["ArtifactsFilesPane"]
