"""Live filter-session behavior for the commits pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from textual.worker import Worker

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.vcs_log.filter_query import (
    CommitFilterQueryError,
    commit_repo_matches,
    compile_commit_matcher,
    parse_commit_filter_query,
    to_query_string,
)
from sase.vcs_log.models import VcsLogResult

from .commit_filter_bar import CommitFilterBar
from .commit_filters import CommitLogFilterValues
from .commits_collection import (
    AuthoritativeCommitSnapshot,
    CommitCollectionSpec,
    CommitScopeKey,
    snapshot_covers,
)
from .commits_timeline import CommitsTimeline

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


FILTER_DEBOUNCE_S = 0.3


class CommitsFilteringMixin(_MixinBase):
    """Own inline filtering, local previews, and query reconciliation."""

    filters: CommitLogFilterValues
    result: VcsLogResult | None
    _generation: int
    _authoritative_results: dict[
        tuple[CommitScopeKey, CommitLogFilterValues], VcsLogResult
    ]
    _preview_base: AuthoritativeCommitSnapshot | None
    _collection_worker: Worker[VcsLogResult] | None
    _collection_spec_in_flight: CommitCollectionSpec | None
    _filter_debouncer: DetailPanelDebouncer | None
    _filter_session_open: bool
    _filter_restore_values: CommitLogFilterValues | None
    _filter_restore_result: VcsLogResult | None
    _live_filter_values: CommitLogFilterValues | None
    _pending_filter_values: CommitLogFilterValues | None
    _filter_query_error: CommitFilterQueryError | None

    if TYPE_CHECKING:

        def _authoritative_snapshot(
            self,
            values: CommitLogFilterValues,
        ) -> AuthoritativeCommitSnapshot | None: ...

        def _display_result(
            self,
            result: VcsLogResult,
            *,
            live_preview: bool = False,
        ) -> None: ...

        def _refresh_info(self) -> None: ...

        def _schedule_collection(self) -> None: ...

        def _scope_key(self) -> CommitScopeKey: ...

    def _init_commits_filtering(self) -> None:
        self._filter_debouncer = None
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_result = None
        self._live_filter_values = None
        self._pending_filter_values = None
        self._filter_query_error = None

    def _filtered_result(
        self,
        result: VcsLogResult,
        values: CommitLogFilterValues,
    ) -> VcsLogResult:
        aliases = {repo.name: repo.aliases for repo in result.repos}
        matcher = compile_commit_matcher(values, repo_aliases=aliases)
        commits = tuple(entry for entry in result.commits if matcher(entry))
        if values.limit > 0:
            commits = commits[: values.limit]
        metadata_values = replace(values, repos=())
        repos = tuple(
            repo
            for repo in result.repos
            if commit_repo_matches(metadata_values, repo.name, repo.aliases)
        )
        repo_names = frozenset(repo.name for repo in repos)
        remote_states = tuple(
            state for state in result.remote_states if state.name in repo_names
        )
        if (
            commits == result.commits
            and repos == result.repos
            and remote_states == result.remote_states
        ):
            return result
        return replace(
            result,
            repos=repos,
            commits=commits,
            remote_states=remote_states,
        )

    def _apply_live_preview(self, values: CommitLogFilterValues) -> None:
        snapshot = self._authoritative_snapshot(values)
        bar = self.query_one(CommitFilterBar)
        if snapshot is None:
            bar.set_status(None, exact=False, error=None)
            return
        preview = self._filtered_result(snapshot.result, values)
        self._display_result(preview, live_preview=True)
        bar.set_status(
            len(preview.commits),
            exact=snapshot_covers(snapshot, values),
            error=None,
        )

    def _set_filter_completion_sources(self, result: VcsLogResult) -> None:
        results: tuple[VcsLogResult, ...] = (result,)
        base = self._preview_base
        if base is not None and base.scope_key == self._scope_key():
            results = (base.result, result)
        repos = tuple(
            source
            for source_result in results
            for repo in source_result.repos
            for source in (repo.name, *repo.aliases)
        )
        authors = tuple(
            entry.commit.author_name
            for source_result in results
            for entry in source_result.commits
            if entry.commit.author_name
        )
        self.query_one(CommitFilterBar).set_completion_sources(repos, authors)

    def _filter_reconciliation_blocked(self) -> bool:
        if not self._filter_session_open:
            return False
        return self._filter_query_error is not None or bool(
            self._filter_debouncer is not None and self._filter_debouncer.is_pending
        )

    def show_filters(self) -> None:
        """Open and focus the inline commit filter bar."""
        bar = self.query_one(CommitFilterBar)
        if self._filter_session_open:
            bar.query_one("#commit-filter-input").focus()
            return
        self._filter_session_open = True
        self._filter_restore_values = self.filters
        self._filter_restore_result = self.result
        self._live_filter_values = self.filters
        self._pending_filter_values = None
        self._filter_query_error = None
        snapshot = self._authoritative_snapshot(self.filters)
        if snapshot is not None:
            self._set_filter_completion_sources(snapshot.result)
        bar.open(to_query_string(self.filters))
        self._apply_live_preview(self.filters)

    def on_commit_filter_bar_query_changed(
        self,
        event: CommitFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        try:
            values = parse_commit_filter_query(event.text)
        except CommitFilterQueryError as exc:
            # Prevent an already-running collection for the last valid query
            # from landing over the inline error state.
            self._generation += 1
            self._filter_query_error = exc
            self._pending_filter_values = None
            if self._filter_debouncer is not None:
                self._filter_debouncer.cancel()
            self.query_one(CommitFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            return

        self._filter_query_error = None
        if values != self._live_filter_values:
            # Invalidate an in-flight collection immediately, without starting
            # any work on the keystroke path. The debouncer schedules the final
            # valid query after the user pauses.
            self._generation += 1
        self._live_filter_values = values
        self._pending_filter_values = values
        self._apply_live_preview(values)

        if self._filter_debouncer is None:
            self._reconcile_live_filter(values, self._generation)
            return
        generation = self._generation

        def _reconcile() -> None:
            self._reconcile_live_filter(values, generation)

        self._filter_debouncer.schedule(_reconcile)

    def _reconcile_live_filter(
        self,
        values: CommitLogFilterValues,
        generation: int,
    ) -> None:
        if (
            not self._filter_session_open
            or self._filter_query_error is not None
            or self._live_filter_values != values
            or self._generation != generation
        ):
            return
        self.filters = values
        self._pending_filter_values = None
        self._refresh_info()
        cached = self._authoritative_results.get((self._scope_key(), values))
        if cached is not None:
            self._apply_live_preview(values)
            return
        if not self._collection_matches(values):
            self._schedule_collection()

    def _collection_matches(self, values: CommitLogFilterValues) -> bool:
        worker = self._collection_worker
        spec = self._collection_spec_in_flight
        return bool(
            worker is not None
            and worker.is_running
            and spec is not None
            and spec.generation == self._generation
            and spec.scope_key == self._scope_key()
            and spec.filters == values
        )

    def on_commit_filter_bar_submitted(
        self,
        event: CommitFilterBar.Submitted,
    ) -> None:
        event.stop()
        try:
            values = parse_commit_filter_query(event.text)
        except CommitFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(CommitFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            self.notify(exc.message, severity="error")
            return

        if values != self._live_filter_values:
            self._generation += 1
        self._live_filter_values = values
        self.filters = values
        self._close_filter_session()
        self.query_one("#commits-timeline", CommitsTimeline).focus()
        self._refresh_info()

        cached = self._authoritative_results.get((self._scope_key(), values))
        if cached is not None:
            self._display_result(self._filtered_result(cached, values))
        elif not self._collection_matches(values):
            self._schedule_collection()

    def on_commit_filter_bar_dismissed(
        self,
        event: CommitFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore_values = self._filter_restore_values or self.filters
        restore_result = self._filter_restore_result
        self._generation += 1
        self.filters = restore_values
        self._close_filter_session()
        self.query_one("#commits-timeline", CommitsTimeline).focus()

        cached = self._authoritative_results.get((self._scope_key(), restore_values))
        if cached is not None:
            self._display_result(self._filtered_result(cached, restore_values))
        elif restore_result is not None:
            self._display_result(restore_result)
            self._schedule_collection()
        else:
            self._refresh_info()
            self._schedule_collection()

    def _close_filter_session(self) -> None:
        if self._filter_debouncer is not None:
            self._filter_debouncer.cancel()
        self.query_one(CommitFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_result = None
        self._live_filter_values = None
        self._pending_filter_values = None
        self._filter_query_error = None


__all__ = ["CommitsFilteringMixin", "FILTER_DEBOUNCE_S"]
