"""Collection workers and authoritative result caching for the commits pane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import TYPE_CHECKING, Any, cast

from textual.worker import Worker, WorkerState

from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)
from sase.vcs_log.models import VcsLogResult

from .commit_filters import CommitLogFilterValues
from .commits_timeline import CommitsTimeline
from .query_rows import build_commits_query_index

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


CommitCollector = Callable[..., VcsLogResult]
CommitScopeKey = tuple[str | None, bool]


@dataclass(frozen=True)
class CommitCollectionSpec:
    generation: int
    filters: CommitLogFilterValues

    @property
    def project_scope(self) -> str | None:
        return self.filters.project

    @property
    def all_projects(self) -> bool:
        return self.filters.project is None

    @property
    def scope_key(self) -> CommitScopeKey:
        return _scope_key_for(self.filters)


@dataclass(frozen=True)
class AuthoritativeCommitSnapshot:
    scope_key: CommitScopeKey
    filters: CommitLogFilterValues
    collection_limit: int
    result: VcsLogResult
    query_index: ArtifactQueryIndex | None = None


@dataclass(frozen=True)
class CommitCollectionPayload:
    result: VcsLogResult
    query_index: ArtifactQueryIndex
    initial_query_result: ArtifactQueryResult


class CommitsCollectionMixin(_MixinBase):
    """Own commit collection, invalidation, and authoritative snapshots."""

    _collector: CommitCollector
    filters: CommitLogFilterValues
    result: VcsLogResult | None
    _generation: int
    _collection_worker: Worker[Any] | None
    _collection_generation: int | None
    _collection_spec_in_flight: CommitCollectionSpec | None
    _collection_pending: bool
    _collection_pending_force_fetch: bool
    _authoritative_results: dict[
        tuple[CommitScopeKey, CommitLogFilterValues], VcsLogResult
    ]
    _authoritative_query_indexes: dict[int, ArtifactQueryIndex]
    _preview_base: AuthoritativeCommitSnapshot | None
    _filter_session_open: bool
    _live_filter_values: CommitLogFilterValues | None
    _query_profile: Any
    _query_session: Any
    _query_result_pending: bool

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
            *,
            resolve_fresh_bounds: bool = False,
        ) -> VcsLogResult: ...

        def _refresh_info(self) -> None: ...

        def _set_filter_completion_sources(self, result: VcsLogResult) -> None: ...

        def _set_result_status(
            self,
            result: VcsLogResult,
            *,
            exact: bool,
            values: CommitLogFilterValues,
        ) -> None: ...

        def _row_query_string(self, values: CommitLogFilterValues) -> str: ...

    def _init_commits_collection(
        self,
        collector: CommitCollector,
        *,
        initial_filters: CommitLogFilterValues | None = None,
    ) -> None:
        self._collector = collector
        self.filters = initial_filters or CommitLogFilterValues()
        self.result = None
        self._generation = 0
        self._collection_worker = None
        self._collection_generation = None
        self._collection_spec_in_flight = None
        self._collection_pending = False
        self._collection_pending_force_fetch = False
        self._authoritative_results = {}
        self._authoritative_query_indexes: dict[int, ArtifactQueryIndex] = {}
        self._preview_base = None

    @property
    def project_scope(self) -> str | None:
        """Return the query-owned project scope."""
        return self.filters.project

    @property
    def all_projects(self) -> bool:
        """Return whether the query requests a true all-project collection."""
        return self.filters.project is None

    def _scope_key(
        self,
        values: CommitLogFilterValues | None = None,
    ) -> CommitScopeKey:
        return _scope_key_for(values or self.filters)

    def _collection_spec(self) -> CommitCollectionSpec:
        return CommitCollectionSpec(
            generation=self._generation,
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
            project_scope=spec.project_scope,
            include_sidecars=spec.filters.sidecar,
            no_fetch=not force_fetch,
            force_fetch=force_fetch,
        )

    def _collect_payload(
        self,
        spec: CommitCollectionSpec,
        *,
        force_fetch: bool,
    ) -> CommitCollectionPayload:
        result = self._collect(spec, force_fetch=force_fetch)
        query_index = build_commits_query_index(
            result,
            pane_id=self._query_profile.pane_id,
            generation=spec.generation,
            profile=self._query_profile,
        )
        query_result = evaluate_artifact_query_many(
            self._row_query_string(spec.filters),
            query_index,
        )
        return CommitCollectionPayload(
            result=result,
            query_index=query_index,
            initial_query_result=query_result,
        )

    def _schedule_collection(self, *, force_fetch: bool = False) -> None:
        if not self.artifacts_active or not self.is_mounted:
            return
        worker = self._collection_worker
        if worker is not None and worker.is_running:
            self._collection_pending = True
            self._collection_pending_force_fetch = (
                self._collection_pending_force_fetch or force_fetch
            )
            self._refresh_info()
            return
        spec = self._collection_spec()
        self._collection_generation = spec.generation
        self._collection_spec_in_flight = spec
        self._collection_worker = self.run_worker(
            lambda spec=spec, force_fetch=force_fetch: self._collect_payload(
                spec,
                force_fetch=force_fetch,
            ),
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
        pending_force_fetch = self._collection_pending_force_fetch
        if event.state == WorkerState.SUCCESS and not pending and spec is not None:
            payload = event.worker.result
            if isinstance(payload, CommitCollectionPayload):
                self._apply_result(
                    payload.result,
                    spec=spec,
                    query_index=payload.query_index,
                    initial_query_result=payload.initial_query_result,
                )
            else:
                self._apply_result(cast(VcsLogResult, payload), spec=spec)
        elif event.state == WorkerState.ERROR and not pending:
            self._show_collection_error(event.worker.error)

        self._collection_pending = False
        self._collection_pending_force_fetch = False
        self._refresh_info()
        if (
            pending
            and self.artifacts_active
            and not self._filter_reconciliation_blocked()
        ):
            self._schedule_collection(force_fetch=pending_force_fetch)

    def _apply_result(
        self,
        result: VcsLogResult,
        *,
        spec: CommitCollectionSpec | None = None,
        query_index: ArtifactQueryIndex | None = None,
        initial_query_result: ArtifactQueryResult | None = None,
    ) -> None:
        spec = spec or self._collection_spec()
        if initial_query_result is not None:
            self._query_session.remember(initial_query_result)
        self._remember_authoritative_result(spec, result, query_index=query_index)
        displayed = self._filtered_result(result, spec.filters)
        self._display_result(displayed)
        if not self._filter_session_open:
            self._set_result_status(
                displayed,
                exact=not self._query_result_pending,
                values=spec.filters,
            )
        else:
            self._set_filter_completion_sources(result)
            if self._live_filter_values == spec.filters:
                self._set_result_status(
                    displayed,
                    exact=not self._query_result_pending,
                    values=spec.filters,
                )
            elif self._live_filter_values is not None:
                self._apply_live_preview(self._live_filter_values)

    def _remember_authoritative_result(
        self,
        spec: CommitCollectionSpec,
        result: VcsLogResult,
        *,
        query_index: ArtifactQueryIndex | None = None,
    ) -> None:
        key = (spec.scope_key, spec.filters)
        self._authoritative_results[key] = result
        if query_index is not None:
            self._authoritative_query_indexes[id(result)] = query_index
        # A filter session can produce many queries. Bound the revert/exact
        # cache while retaining insertion-order recency.
        if len(self._authoritative_results) > 32:
            oldest = next(iter(self._authoritative_results))
            if oldest != key:
                old_result = self._authoritative_results.pop(oldest, None)
                if old_result is not None:
                    self._authoritative_query_indexes.pop(id(old_result), None)

        candidate = AuthoritativeCommitSnapshot(
            spec.scope_key,
            spec.filters,
            _backend_collection_limit(spec.filters),
            result,
            query_index,
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
        scope_key = self._scope_key(values)
        exact = self._authoritative_results.get((scope_key, values))
        if exact is not None:
            return AuthoritativeCommitSnapshot(
                scope_key,
                values,
                _backend_collection_limit(values),
                exact,
                self._authoritative_query_indexes.get(id(exact)),
            )
        base = self._preview_base
        if base is not None and base.scope_key == scope_key:
            return base
        return None

    def _query_index_for_result(
        self,
        result: VcsLogResult,
    ) -> ArtifactQueryIndex | None:
        return self._authoritative_query_indexes.get(id(result))

    def _show_collection_error(self, error: BaseException | None) -> None:
        message = str(error).strip() if error is not None else "unknown error"
        self.query_one("#stitches-timeline", CommitsTimeline).update_result(
            VcsLogResult((), (), (f"Unable to load commits: {message}",))
        )
        self.notify(f"Unable to load commits: {message}", severity="error")


def _snapshot_breadth(
    snapshot: AuthoritativeCommitSnapshot,
) -> tuple[int, int, int, int, int]:
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
    merge_breadth = 1 if filters.merges == "show" else 0
    return (-constraints, int(filters.sidecar), merge_breadth, unlimited, limit)


def snapshot_covers(
    snapshot: AuthoritativeCommitSnapshot,
    values: CommitLogFilterValues,
) -> bool:
    if snapshot.scope_key != _scope_key_for(values):
        return False
    if snapshot.result.potentially_truncated:
        return False
    if snapshot.filters == values:
        return True
    base = snapshot.filters
    if values.sidecar and not base.sidecar:
        return False
    if base.merges != "show" and base.merges != values.merges:
        return False
    if _same_backend_constraints(base, values):
        return True
    backend_unfiltered = not (
        base.repos
        or base.excluded_repos
        or base.authors
        or base.since is not None
        or base.until is not None
    )
    return backend_unfiltered


def _same_backend_constraints(
    base: CommitLogFilterValues,
    values: CommitLogFilterValues,
) -> bool:
    return (
        base.project == values.project
        and base.repos == values.repos
        and base.excluded_repos == values.excluded_repos
        and base.authors == values.authors
        and base.since == values.since
        and base.until == values.until
    )


def _backend_collection_limit(values: CommitLogFilterValues) -> int:
    presentation_exclusions = values.excluded_authors or values.excluded_text
    return 0 if values.text or presentation_exclusions else values.limit


def _scope_key_for(values: CommitLogFilterValues) -> CommitScopeKey:
    project = values.project
    return (project, project is None)


__all__ = [
    "AuthoritativeCommitSnapshot",
    "CommitCollectionSpec",
    "CommitCollectionPayload",
    "CommitCollector",
    "CommitScopeKey",
    "CommitsCollectionMixin",
    "snapshot_covers",
]
