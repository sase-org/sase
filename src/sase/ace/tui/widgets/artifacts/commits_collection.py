"""Collection workers and authoritative result caching for the commits pane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import TYPE_CHECKING, cast

from textual.worker import Worker, WorkerState

from sase.vcs_log.models import VcsLogResult

from .commit_filter_bar import CommitFilterBar
from .commit_filters import CommitLogFilterValues
from .commits_timeline import CommitsTimeline

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


CommitCollector = Callable[..., VcsLogResult]
CommitScopeKey = tuple[str | None, bool]


@dataclass(frozen=True)
class CommitCollectionSpec:
    generation: int
    project_scope: str | None
    all_projects: bool
    filters: CommitLogFilterValues

    @property
    def scope_key(self) -> CommitScopeKey:
        return (self.project_scope, self.all_projects)


@dataclass(frozen=True)
class AuthoritativeCommitSnapshot:
    scope_key: CommitScopeKey
    filters: CommitLogFilterValues
    collection_limit: int
    result: VcsLogResult


class CommitsCollectionMixin(_MixinBase):
    """Own commit collection, invalidation, and authoritative snapshots."""

    _collector: CommitCollector
    project_scope: str | None
    all_projects: bool
    filters: CommitLogFilterValues
    result: VcsLogResult | None
    _generation: int
    _collection_worker: Worker[VcsLogResult] | None
    _collection_generation: int | None
    _collection_spec_in_flight: CommitCollectionSpec | None
    _collection_pending: bool
    _authoritative_results: dict[
        tuple[CommitScopeKey, CommitLogFilterValues], VcsLogResult
    ]
    _preview_base: AuthoritativeCommitSnapshot | None
    _filter_session_open: bool
    _live_filter_values: CommitLogFilterValues | None

    if TYPE_CHECKING:

        @property
        def artifacts_active(self) -> bool: ...

        def _apply_live_preview(self, values: CommitLogFilterValues) -> None: ...

        def _display_result(
            self,
            result: VcsLogResult,
            *,
            live_preview: bool = False,
        ) -> None: ...

        def _filter_reconciliation_blocked(self) -> bool: ...

        def _filtered_result(
            self,
            result: VcsLogResult,
            values: CommitLogFilterValues,
        ) -> VcsLogResult: ...

        def _refresh_info(self) -> None: ...

        def _set_filter_completion_sources(self, result: VcsLogResult) -> None: ...

    def _init_commits_collection(
        self,
        collector: CommitCollector,
        *,
        initial_filters: CommitLogFilterValues | None = None,
    ) -> None:
        self._collector = collector
        self.project_scope = None
        self.all_projects = False
        self.filters = initial_filters or CommitLogFilterValues()
        self.result = None
        self._generation = 0
        self._collection_worker = None
        self._collection_generation = None
        self._collection_spec_in_flight = None
        self._collection_pending = False
        self._authoritative_results = {}
        self._preview_base = None

    def _state_changed(self) -> None:
        if (
            self._preview_base is not None
            and self._preview_base.scope_key != self._scope_key()
        ):
            self._preview_base = None
        self._generation += 1
        if self.artifacts_active:
            self._schedule_collection()

    def _scope_key(self) -> CommitScopeKey:
        return (self.project_scope, self.all_projects)

    def _collection_spec(self) -> CommitCollectionSpec:
        return CommitCollectionSpec(
            generation=self._generation,
            project_scope=self.project_scope,
            all_projects=self.all_projects,
            filters=self.filters,
        )

    def _collect(
        self, spec: CommitCollectionSpec, *, force_fetch: bool
    ) -> VcsLogResult:
        # Subject terms are presentation-only, so collect the complete
        # author/date/repo-filtered set before the UI applies the row cap.
        # Otherwise older subject matches can be hidden behind newer misses.
        collection_limit = _backend_collection_limit(spec.filters)
        return self._collector(
            cwd=os.getcwd(),
            limit=collection_limit,
            filter_spec=spec.filters.backend_filter_spec(),
            repo_filters=spec.filters.repos,
            exclude_repo_filters=spec.filters.excluded_repos,
            all_projects=spec.all_projects,
            project_scope=None if spec.all_projects else spec.project_scope,
            include_sidecars=spec.filters.sidecar,
            no_fetch=not force_fetch,
            force_fetch=force_fetch,
        )

    def _schedule_collection(self) -> None:
        if not self.artifacts_active or not self.is_mounted:
            return
        worker = self._collection_worker
        if worker is not None and worker.is_running:
            self._collection_pending = True
            self._refresh_info()
            return
        spec = self._collection_spec()
        self._collection_generation = spec.generation
        self._collection_spec_in_flight = spec
        self._collection_worker = self.run_worker(
            lambda spec=spec: self._collect(spec, force_fetch=False),
            thread=True,
            group="artifacts-commits-collection",
            exclusive=True,
            exit_on_error=False,
        )
        self._refresh_info()

    def _on_collection_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        generation = self._collection_generation
        spec = self._collection_spec_in_flight
        self._collection_worker = None
        self._collection_generation = None
        self._collection_spec_in_flight = None
        stale = generation != self._generation
        pending = self._collection_pending or stale
        if event.state == WorkerState.SUCCESS and not pending and spec is not None:
            self._apply_result(cast(VcsLogResult, event.worker.result), spec=spec)
        elif event.state == WorkerState.ERROR and not pending:
            self._show_collection_error(event.worker.error)

        self._collection_pending = False
        self._refresh_info()
        if (
            pending
            and self.artifacts_active
            and not self._filter_reconciliation_blocked()
        ):
            self._schedule_collection()

    def _apply_result(
        self,
        result: VcsLogResult,
        *,
        spec: CommitCollectionSpec | None = None,
    ) -> None:
        spec = spec or self._collection_spec()
        self._remember_authoritative_result(spec, result)
        displayed = self._filtered_result(result, spec.filters)
        self._display_result(displayed)
        if not self._filter_session_open:
            self.query_one(CommitFilterBar).set_status(
                len(displayed.commits),
                exact=True,
                error=None,
            )
        else:
            self._set_filter_completion_sources(result)
            if self._live_filter_values == spec.filters:
                self.query_one(CommitFilterBar).set_status(
                    len(displayed.commits),
                    exact=True,
                    error=None,
                )
            elif self._live_filter_values is not None:
                self._apply_live_preview(self._live_filter_values)

    def _remember_authoritative_result(
        self,
        spec: CommitCollectionSpec,
        result: VcsLogResult,
    ) -> None:
        key = (spec.scope_key, spec.filters)
        self._authoritative_results[key] = result
        # A filter session can produce many queries. Bound the revert/exact
        # cache while retaining insertion-order recency.
        if len(self._authoritative_results) > 32:
            oldest = next(iter(self._authoritative_results))
            if oldest != key:
                self._authoritative_results.pop(oldest, None)

        candidate = AuthoritativeCommitSnapshot(
            spec.scope_key,
            spec.filters,
            _backend_collection_limit(spec.filters),
            result,
        )
        current = self._preview_base
        if (
            current is None
            or current.scope_key != candidate.scope_key
            or _snapshot_breadth(candidate) > _snapshot_breadth(current)
        ):
            self._preview_base = candidate

    def _authoritative_snapshot(
        self,
        values: CommitLogFilterValues,
    ) -> AuthoritativeCommitSnapshot | None:
        scope_key = self._scope_key()
        exact = self._authoritative_results.get((scope_key, values))
        if exact is not None:
            return AuthoritativeCommitSnapshot(
                scope_key,
                values,
                _backend_collection_limit(values),
                exact,
            )
        base = self._preview_base
        if base is not None and base.scope_key == scope_key:
            return base
        return None

    def _show_collection_error(self, error: BaseException | None) -> None:
        message = str(error).strip() if error is not None else "unknown error"
        self.query_one("#commits-timeline", CommitsTimeline).update_result(
            VcsLogResult((), (), (f"Unable to load commits: {message}",))
        )
        self.notify(f"Unable to load commits: {message}", severity="error")


def _snapshot_breadth(
    snapshot: AuthoritativeCommitSnapshot,
) -> tuple[int, int, int, int]:
    filters = snapshot.filters
    constraints = (
        len(filters.repos)
        + len(filters.excluded_repos)
        + len(filters.authors)
        + int(filters.since is not None)
        + int(filters.until is not None)
    )
    unlimited = int(snapshot.collection_limit == 0)
    limit = snapshot.collection_limit if snapshot.collection_limit > 0 else 2**31
    return (-constraints, int(filters.sidecar), unlimited, limit)


def snapshot_covers(
    snapshot: AuthoritativeCommitSnapshot,
    values: CommitLogFilterValues,
) -> bool:
    if snapshot.filters == values:
        return True
    base = snapshot.filters
    if values.sidecar and not base.sidecar:
        return False
    backend_unfiltered = not (
        base.repos
        or base.excluded_repos
        or base.authors
        or base.since is not None
        or base.until is not None
    )
    truncated = (
        snapshot.collection_limit > 0
        and len(snapshot.result.commits) >= snapshot.collection_limit
    )
    return backend_unfiltered and not truncated


def _backend_collection_limit(values: CommitLogFilterValues) -> int:
    presentation_exclusions = values.excluded_authors or values.excluded_text
    return 0 if values.text or presentation_exclusions else values.limit


__all__ = [
    "AuthoritativeCommitSnapshot",
    "CommitCollectionSpec",
    "CommitCollector",
    "CommitScopeKey",
    "CommitsCollectionMixin",
    "snapshot_covers",
]
