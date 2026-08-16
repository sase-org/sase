"""Index-backed list and lifecycle for the Artifacts Files pane."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static
from textual.worker import Worker

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.keymaps import (
    KeymapRegistry,
    load_keymap_registry,
)
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)
from sase.core.artifact_relations import RelationIndex
from sase.project_display_names import ProjectRefDisplaySnapshot

from ...relations import build_files_relation_index
from ...relations._support import relation_index_if_enabled
from .file_filter_bar import FileFilterBar
from .files_data import (
    FILES_FIRST_PAGE_LIMIT,
    FilesSnapshot,
    load_files_snapshot,
)
from .files_detail_panel import FilesDetailMixin
from .files_filter_session import FilesFilterSessionMixin
from .files_filtering import to_query_string
from .files_navigation import FilesNavigationMixin, FilesOptionList
from .files_options import FilesOptionsMixin
from .files_query_index import FilesQueryIndexMixin
from .files_selection import FilesSelectionMixin
from .group_fold_navigation import ArtifactGroupFoldMixin
from ..._artifact_tab_model import ArtifactsPaneContract
from .query_rows import build_files_query_index
from .query_session import ArtifactQuerySession
from .relation_panel import RelationPanel, RelationPanelHostMixin
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest


@dataclass(frozen=True, slots=True)
class _FilesSnapshotResult:
    snapshot: FilesSnapshot
    query_index: ArtifactQueryIndex
    initial_query_result: ArtifactQueryResult | None
    relation_index: RelationIndex | None = None


class ArtifactsFilesPane(
    ArtifactGroupFoldMixin,
    FilesDetailMixin,
    FilesFilterSessionMixin,
    FilesNavigationMixin,
    FilesOptionsMixin,
    FilesQueryIndexMixin,
    FilesSelectionMixin,
    RelationPanelHostMixin,
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
        self._query_session = ArtifactQuerySession(
            self,
            group="artifacts-files-query",
            on_current_result=lambda _result: self._refresh_options(
                preferred_target=self.selected_entry_target()
            ),
        )
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._extension_generation = 0
        self._init_files_query_index()
        self._init_files_navigation()
        self._init_files_selection()
        self._init_files_options()
        self._init_files_detail()
        self._init_files_filter_session()
        self._init_group_fold()

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
                yield RelationPanel(
                    id="files-relation-panel",
                    classes="artifacts-relation-panel",
                )
            detail_panel = Vertical(id="files-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="files-detail-scroll"):
                    yield Static("", id="files-detail")
        yield Static(self._hints_text(), id="files-hints")

    def on_mount(self) -> None:
        self._start_detail_debouncer()
        self._refresh_options()

    def on_unmount(self) -> None:
        self._extension_generation += 1
        self._cancel_detail_debouncer()
        cancel_pump_free_tasks(self)
        self._query_session.clear()
        self._cancel_query_index_worker()
        self._cancel_snapshot_worker()
        self._cancel_detail_worker()

    def on_deactivate(self) -> None:
        self._cancel_detail_debouncer()

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
            relation_index=relation_index_if_enabled(
                self.contract,
                lambda contract: build_files_relation_index(
                    snapshot, contract=contract
                ),
            ),
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
        self._relation_index = result.relation_index
        self._query_index = result.query_index
        if result.initial_query_result is not None:
            self._query_session.remember(result.initial_query_result)
        self._load_error = result.snapshot.load_error
        self._invalidate_detail_cache()
        self._reset_version_indices(result.snapshot.rows)
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


__all__ = ["ArtifactsFilesPane"]
