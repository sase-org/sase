"""Live filter-session behavior for the commits pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from textual.worker import Worker

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.vcs_log.dates import normalize_reference_time
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
from .commits_rendering import commit_filter_chips
from .commits_timeline import CommitsTimeline

if TYPE_CHECKING:
    from sase.project_display_names import ProjectRefDisplaySnapshot
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
    _project_ref_display: ProjectRefDisplaySnapshot

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

        def _filter_chips(self) -> tuple[str, ...]: ...

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
        *,
        resolve_fresh_bounds: bool = False,
    ) -> VcsLogResult:
        aliases = {repo.name: repo.aliases for repo in result.repos}
        wanted_spec = values.backend_filter_spec()
        collected_spec = result.filter_spec
        resolved_filters = None
        if (
            not resolve_fresh_bounds
            and collected_spec is not None
            and collected_spec.since == wanted_spec.since
            and collected_spec.until == wanted_spec.until
        ):
            resolved_filters = result.resolved_filters
        reference = None if resolved_filters is not None else normalize_reference_time()
        matcher = compile_commit_matcher(
            values,
            repo_aliases=aliases,
            now=reference,
            resolved_filters=resolved_filters,
        )
        repos = tuple(
            repo
            for repo in result.repos
            if (values.sidecar or repo.kind != "sidecar")
            and commit_repo_matches(values, repo.name, repo.aliases)
        )
        repo_names = frozenset(repo.name for repo in repos)
        matching_commits = tuple(
            entry
            for entry in result.commits
            if entry.repo in repo_names and matcher(entry)
        )
        visible_truncated = values.limit > 0 and len(matching_commits) > values.limit
        commits = matching_commits
        if values.limit > 0:
            commits = commits[: values.limit]
        remote_states = tuple(
            state for state in result.remote_states if state.name in repo_names
        )
        if (
            commits == result.commits
            and repos == result.repos
            and remote_states == result.remote_states
            and not visible_truncated
        ):
            return result
        return replace(
            result,
            repos=repos,
            commits=commits,
            remote_states=remote_states,
            aggregate_truncated=result.aggregate_truncated or visible_truncated,
        )

    def _set_result_status(
        self,
        result: VcsLogResult,
        *,
        exact: bool,
        values: CommitLogFilterValues,
    ) -> None:
        """Render one truthful coverage state for previews and final results."""
        capped = result.potentially_truncated
        bar = self.query_one(CommitFilterBar)
        bar.set_status(
            len(result.commits),
            exact=exact and not capped,
            error=None,
            coverage_label="capped" if capped else None,
            lower_bound=capped,
        )
        if not self._filter_session_open:
            bar.set_query(" ".join(commit_filter_chips(values)))

    def _apply_live_preview(self, values: CommitLogFilterValues) -> None:
        snapshot = self._authoritative_snapshot(values)
        bar = self.query_one(CommitFilterBar)
        if snapshot is None:
            bar.set_status(None, exact=False, error=None)
            return
        preview = self._filtered_result(
            snapshot.result,
            values,
            resolve_fresh_bounds=True,
        )
        self._display_result(preview, live_preview=True)
        self._set_result_status(
            preview,
            exact=snapshot_covers(snapshot, values),
            values=values,
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

    def _show_filter_query_error(self, error: CommitFilterQueryError) -> None:
        """Restore the pre-edit view while keeping an invalid query editable."""
        self._generation += 1
        self._filter_query_error = error
        self._live_filter_values = None
        self._pending_filter_values = None
        if self._filter_debouncer is not None:
            self._filter_debouncer.cancel()

        restore_values = self._filter_restore_values
        restore_result = self._filter_restore_result
        if restore_values is not None:
            self.filters = restore_values
            cached = self._authoritative_results.get(
                (self._scope_key(), restore_values)
            )
            if cached is not None:
                displayed = self._filtered_result(cached, restore_values)
                self._display_result(displayed)
                self._set_result_status(
                    displayed,
                    exact=True,
                    values=restore_values,
                )
            elif restore_result is not None:
                self._display_result(restore_result)
            else:
                self._refresh_info()

        self.query_one(CommitFilterBar).set_status(
            None,
            exact=False,
            error=error,
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
        bar.open(" ".join(self._filter_chips()))
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
            self._show_filter_query_error(exc)
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
            self._show_filter_query_error(exc)
            self.notify(exc.message, severity="error")
            return

        self._commit_filter_values(values, close_session=True)

    def _commit_filter_values(
        self,
        values: CommitLogFilterValues,
        *,
        close_session: bool,
    ) -> None:
        """Commit validated values and reconcile their authoritative result."""
        old_project = self.filters.project
        project = self._project_ref_display.label_for_ref(values.project)
        if project != values.project:
            values = replace(values, project=project)
        if values.project != old_project:
            clear_marks = getattr(
                self.app,
                "_clear_artifacts_marks_for_subtab",
                None,
            )
            if callable(clear_marks):
                clear_marks("commits")
        if values != self._live_filter_values:
            self._generation += 1
        self._live_filter_values = values
        self.filters = values
        self.query_one(CommitFilterBar).set_query(to_query_string(values))
        if close_session:
            self._close_filter_session()
            self.query_one("#commits-timeline", CommitsTimeline).focus()
        self._refresh_info()

        cached = self._authoritative_results.get((self._scope_key(), values))
        if cached is not None:
            displayed = self._filtered_result(cached, values)
            self._display_result(displayed)
            self._set_result_status(displayed, exact=True, values=values)
            return

        snapshot = self._authoritative_snapshot(values)
        if snapshot is not None:
            displayed = self._filtered_result(
                snapshot.result,
                values,
                resolve_fresh_bounds=True,
            )
            self._display_result(
                displayed,
                live_preview=True,
            )
            self._set_result_status(
                displayed,
                exact=snapshot_covers(snapshot, values),
                values=values,
            )
        if not self._collection_matches(values):
            self._schedule_collection()

    def on_commit_filter_bar_dismissed(
        self,
        event: CommitFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore_values = self._filter_restore_values or self.filters
        restore_result = self._filter_restore_result
        if (
            self._filter_query_error is not None
            or self._live_filter_values != restore_values
        ):
            self._generation += 1
        self.filters = restore_values
        self._close_filter_session()
        self.query_one("#commits-timeline", CommitsTimeline).focus()

        cached = self._authoritative_results.get((self._scope_key(), restore_values))
        if cached is not None:
            displayed = self._filtered_result(cached, restore_values)
            self._display_result(displayed)
            self._set_result_status(
                displayed,
                exact=True,
                values=restore_values,
            )
        elif restore_result is not None:
            self._display_result(restore_result)
            self._set_result_status(
                restore_result,
                exact=True,
                values=restore_values,
            )
            self._schedule_collection()
        else:
            self._refresh_info()
            self._schedule_collection()

    def _close_filter_session(self) -> None:
        if self._filter_debouncer is not None:
            self._filter_debouncer.cancel()
        bar = self.query_one(CommitFilterBar)
        bar.set_query(" ".join(self._filter_chips()))
        bar.close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_result = None
        self._live_filter_values = None
        self._pending_filter_values = None
        self._filter_query_error = None


__all__ = ["CommitsFilteringMixin", "FILTER_DEBOUNCE_S"]
