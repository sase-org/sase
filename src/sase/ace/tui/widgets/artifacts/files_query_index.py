"""Off-thread query-index rebuilds for the Artifacts Files pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.ace.query_profile import CompiledQueryProfile
from sase.core.query_profile_corpus_facade import ArtifactQueryIndex
from sase.project_display_names import ProjectRefDisplaySnapshot

from .entry_navigation import ArtifactEntryTarget
from .files_data import FilesSnapshot
from .query_rows import build_files_query_index
from .query_session import ArtifactQuerySession

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True, slots=True)
class _FilesQueryIndexResult:
    """One completed index rebuild, tagged with the state it was built from."""

    generation: int
    display_generation: int
    query_index: ArtifactQueryIndex


class FilesQueryIndexMixin(_MixinBase):
    """Rebuild the query index off-thread when project labels change."""

    _load_generation: int
    _project_ref_display: ProjectRefDisplaySnapshot
    _project_ref_display_generation: int
    _query_index: ArtifactQueryIndex | None
    _query_index_worker: Worker[Any] | None
    _query_profile: CompiledQueryProfile
    _query_session: ArtifactQuerySession

    if TYPE_CHECKING:

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def _current_snapshot(self) -> FilesSnapshot | None: ...

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

    def _init_files_query_index(self) -> None:
        self._query_index = None
        self._query_index_worker = None
        self._project_ref_display = ProjectRefDisplaySnapshot()
        self._project_ref_display_generation = 0

    def _cancel_query_index_worker(self) -> None:
        worker = self._query_index_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _request_query_index_rebuild(self) -> None:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return
        self._cancel_query_index_worker()
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


__all__ = ["FilesQueryIndexMixin"]
