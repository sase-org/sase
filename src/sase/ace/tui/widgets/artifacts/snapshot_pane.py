"""Shared off-thread snapshot lifecycle for Artifacts list panes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.containers import Vertical
from textual.worker import Worker, WorkerState

from .lifecycle import ArtifactsPaneLifecycle
from .shell import ArtifactsPaneState, ArtifactsShellState, resolve_pane_state


@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    """One coalesced snapshot load request."""

    project: str | None
    force: bool
    full: bool = False
    generation: int = 0


class ArtifactsSnapshotPane(ArtifactsPaneLifecycle, Vertical):
    """Coalesced, last-request-wins snapshot loader.

    Subclasses implement :meth:`_build_snapshot`, :meth:`_accept_snapshot`,
    and :meth:`_apply_snapshot`. Collection always runs in a worker thread;
    this base never reads data on the event loop.
    """

    _collects_snapshots_on_event_loop = False

    def _init_snapshot_lifecycle(self) -> None:
        self._init_artifacts_lifecycle()
        self._snapshot: Any = None
        self._loading = False
        self._loading_full = False
        self._reload_pending = False
        self._force_pending = False
        self._full_pending = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._load_generation = 0
        self._worker_generation = -1
        self._worker_full = False

    def _request_snapshot(self, *, force: bool, full: bool = False) -> None:
        """Coalesce one off-thread load with last-request-wins semantics."""

        if self._loading:
            self._reload_pending = True
            self._force_pending = self._force_pending or force
            self._full_pending = self._full_pending or full
            return
        self._load_generation += 1
        request = self._make_snapshot_request(force=force, full=full)
        self._loading = True
        self._loading_full = full
        self._load_error = None
        self._on_snapshot_started(request)

        def task() -> Any:
            return self._build_snapshot(request)

        worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )
        self._worker = worker
        self._worker_generation = request.generation
        self._worker_full = full

    def _make_snapshot_request(self, *, force: bool, full: bool) -> SnapshotRequest:
        return SnapshotRequest(
            project=getattr(self, "project_scope", None),
            force=force,
            full=full,
            generation=self._load_generation,
        )

    def _build_snapshot(self, request: SnapshotRequest) -> Any:
        raise NotImplementedError

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return result is not None

    def _apply_snapshot(self, result: Any, request: SnapshotRequest) -> None:
        raise NotImplementedError

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        del request

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error

    def _after_snapshot_success(self, result: Any, request: SnapshotRequest) -> None:
        del result, request

    def _handle_auxiliary_worker(self, event: Worker.StateChanged) -> bool:
        del event
        return False

    def _cancel_snapshot_worker(self) -> None:
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def _snapshot_matches_scope(self) -> bool:
        """Return whether ``self._snapshot`` covers the pane's current scope.

        The default treats any cached snapshot as usable content. A subclass
        whose snapshot carries a ``project`` field overrides this so a
        different scope's cached rows are never shown as though they were
        the current scope's content.
        """
        return self._snapshot is not None

    def _snapshot_row_count(self) -> int:
        """Return the row count of the current, scope-matched snapshot."""
        raise NotImplementedError

    def pane_state(self, *, has_active_filter: bool = False) -> ArtifactsPaneState:
        """Resolve this pane's closed shell state from its lifecycle fields."""

        has_content = self._snapshot_matches_scope()
        row_count = self._snapshot_row_count() if has_content else 0
        return resolve_pane_state(
            ArtifactsShellState(
                is_loading=self._loading,
                has_error=self._load_error is not None,
                has_content=has_content,
                row_count=row_count,
                has_active_filter=has_active_filter,
            )
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if self._handle_auxiliary_worker(event):
            return
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        request = SnapshotRequest(
            project=getattr(self, "project_scope", None),
            force=self._force_pending,
            full=self._worker_full,
            generation=self._worker_generation,
        )
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            self._loading_full = False
            result = event.worker.result
            if self._accept_snapshot(result, request):
                self._apply_snapshot(result, request)
                self._after_snapshot_success(result, request)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loading_full = False
            self._on_snapshot_error(
                str(event.worker.error or "Artifacts load failed"),
                request,
            )
        elif event.state == WorkerState.CANCELLED:
            self._loading = False
            self._loading_full = False

        if terminal and self._reload_pending:
            force = self._force_pending
            full = self._full_pending
            self._reload_pending = False
            self._force_pending = False
            self._full_pending = False
            self.call_later(lambda: self._request_snapshot(force=force, full=full))


__all__ = ["ArtifactsPaneState", "ArtifactsSnapshotPane", "SnapshotRequest"]
