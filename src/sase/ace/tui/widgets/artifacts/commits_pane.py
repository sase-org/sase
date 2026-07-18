"""State and worker orchestration for the Artifacts commits pane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import os
from typing import TYPE_CHECKING, Any, cast

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.core.vcs_log_wire import AggregatedCommitWire
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
from .commits_rendering import (
    build_commit_detail,
    build_commit_view_spec,
    build_commits_hints,
    build_commits_info,
    commit_filter_chips,
)
from .commits_timeline import CommitsTimeline
from .entry_navigation import ArtifactEntryTarget
from .panes import ArtifactsPaneLifecycle

if TYPE_CHECKING:
    from sase.ace.tui.actions.task_actions import TrackedTaskCompletion

CommitCollector = Callable[..., VcsLogResult]
CommitDiffLoader = Callable[[CommitViewSpec], str | None]
_ScopeKey = tuple[str | None, bool, bool]
_FILTER_DEBOUNCE_S = 0.3


@dataclass(frozen=True)
class _CollectionSpec:
    generation: int
    project_scope: str | None
    all_projects: bool
    include_sdd: bool
    filters: CommitLogFilterValues

    @property
    def scope_key(self) -> _ScopeKey:
        return (self.project_scope, self.all_projects, self.include_sdd)


@dataclass(frozen=True)
class _AuthoritativeSnapshot:
    scope_key: _ScopeKey
    filters: CommitLogFilterValues
    collection_limit: int
    result: VcsLogResult


class CommitsPane(ArtifactsPaneLifecycle, Vertical):
    """Lazy, cached, interactive view over the existing VCS-log backend."""

    OpenRequested = CommitsTimeline.OpenRequested

    def __init__(
        self,
        *,
        collector: CommitCollector,
        diff_loader: CommitDiffLoader,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self._collector = collector
        self._diff_loader = diff_loader
        self._registry = load_keymap_registry({})
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._project_file: str = ""
        self.all_projects = False
        self.include_sdd = False
        self.filters = CommitLogFilterValues()
        self.result: VcsLogResult | None = None
        self._generation = 0
        self._collection_worker: Worker[VcsLogResult] | None = None
        self._collection_generation: int | None = None
        self._collection_spec_in_flight: _CollectionSpec | None = None
        self._collection_pending = False
        self._authoritative_results: dict[
            tuple[_ScopeKey, CommitLogFilterValues], VcsLogResult
        ] = {}
        self._preview_base: _AuthoritativeSnapshot | None = None
        self._filter_debouncer: DetailPanelDebouncer | None = None
        self._filter_session_open = False
        self._filter_restore_values: CommitLogFilterValues | None = None
        self._filter_restore_result: VcsLogResult | None = None
        self._live_filter_values: CommitLogFilterValues | None = None
        self._pending_filter_values: CommitLogFilterValues | None = None
        self._filter_query_error: CommitFilterQueryError | None = None
        self._selected_commit_index: int | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._diff_worker: Worker[tuple[tuple[str, str], str | None]] | None = None
        self._diff_cache: dict[tuple[str, str], str | None] = {}
        self._diff_loading_key: tuple[str, str] | None = None
        self._syntax_render_cache = LazySyntaxRenderCache()

    def compose(self) -> ComposeResult:
        yield CommitFilterBar(id="commit-filter-bar")
        yield Static(self._build_info(), id="commits-info")
        with Horizontal(id="commits-main"):
            with Vertical(id="commits-list-container"):
                yield CommitsTimeline(id="commits-timeline")
                yield Static(self._hints_text(), id="commits-footer")
            with Vertical(id="commits-detail-container"):
                with VerticalScroll(id="commits-detail-scroll"):
                    yield Static(
                        Text(
                            "Select a commit to inspect its message and diff.",
                            style="dim italic",
                        ),
                        id="commits-detail",
                    )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._filter_debouncer = DetailPanelDebouncer(
            self.app,
            delay_s=_FILTER_DEBOUNCE_S,
        )

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._filter_debouncer is not None:
            self._filter_debouncer.cancel()
        self._cancel_worker(self._collection_worker)
        self._cancel_worker(self._diff_worker)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use configured Commits actions in the pane's hint bar."""
        self._registry = registry
        if self.is_mounted:
            self.query_one("#commits-footer", Static).update(self._hints_text())

    def move_selection(self, step: int) -> None:
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        timeline.focus()
        if step > 0:
            timeline.action_cursor_down()
        else:
            timeline.action_cursor_up()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        return timeline.entry_targets

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        return timeline.selected_entry_target

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select a loaded commit by repository + full SHA identity."""
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        index = timeline.select_entry_target(target)
        if index is None:
            return False
        changed = index != self._selected_commit_index
        self._selected_commit_index = index
        if changed:
            if self._detail_debouncer is None:
                self._render_selected_detail(index)
            else:

                def _render() -> None:
                    self._render_selected_detail(index)

                self._detail_debouncer.schedule(_render)
        return True

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        if self.result is None:
            return
        self.query_one("#commits-timeline", CommitsTimeline).apply_jump_hints(
            hints, self.result
        )

    def clear_entry_jump_hints(self) -> None:
        if self.result is None:
            return
        self.query_one("#commits-timeline", CommitsTimeline).clear_jump_hints(
            self.result
        )

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
        project_file: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._project_file = project_file or ""
        self._refresh_info()
        if changed:
            self._state_changed()

    def on_activate(self) -> None:
        if self.is_mounted:
            self.query_one("#commits-timeline", CommitsTimeline).focus()
        self._schedule_collection()

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_refresh(self) -> None:
        self._schedule_collection()

    def _state_changed(self) -> None:
        if (
            self._preview_base is not None
            and self._preview_base.scope_key != self._scope_key()
        ):
            self._preview_base = None
        self._generation += 1
        if self.artifacts_active:
            self._schedule_collection()

    def _scope_key(self) -> _ScopeKey:
        return (self.project_scope, self.all_projects, self.include_sdd)

    def _collection_spec(self) -> _CollectionSpec:
        return _CollectionSpec(
            generation=self._generation,
            project_scope=self.project_scope,
            all_projects=self.all_projects,
            include_sdd=self.include_sdd,
            filters=self.filters,
        )

    def _collect(self, spec: _CollectionSpec, *, force_fetch: bool) -> VcsLogResult:
        # Subject terms are presentation-only, so collect the complete
        # author/date/repo-filtered set before the UI applies the row cap.
        # Otherwise older subject matches can be hidden behind newer misses.
        collection_limit = _backend_collection_limit(spec.filters)
        return self._collector(
            cwd=os.getcwd(),
            limit=collection_limit,
            filters=spec.filters.backend_filters(),
            repo_filters=spec.filters.repos,
            exclude_repo_filters=spec.filters.excluded_repos,
            all_projects=spec.all_projects,
            project_scope=None if spec.all_projects else spec.project_scope,
            include_sdd=spec.include_sdd,
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

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._collection_worker:
            self._on_collection_worker_changed(event)
        elif event.worker is self._diff_worker:
            self._on_diff_worker_changed(event)

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
        spec: _CollectionSpec | None = None,
    ) -> None:
        spec = spec or self._collection_spec()
        self._remember_authoritative_result(spec, result)
        displayed = self._filtered_result(result, spec.filters)
        self._display_result(displayed)
        if self._filter_session_open:
            self._set_filter_completion_sources(result)
            if self._live_filter_values == spec.filters:
                self.query_one(CommitFilterBar).set_status(
                    len(displayed.commits),
                    exact=True,
                    error=None,
                )
            elif self._live_filter_values is not None:
                self._apply_live_preview(self._live_filter_values)

    def _display_result(
        self,
        result: VcsLogResult,
        *,
        live_preview: bool = False,
    ) -> None:
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("commits")
        self.result = result
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        self._selected_commit_index = timeline.update_result(result)
        self._refresh_info()
        if self._selected_commit_index is not None:
            if live_preview and self._detail_debouncer is not None:
                index = self._selected_commit_index

                def _render() -> None:
                    self._render_selected_detail(index)

                self._detail_debouncer.schedule(_render)
            else:
                self._render_selected_detail(self._selected_commit_index)

    def _remember_authoritative_result(
        self,
        spec: _CollectionSpec,
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

        candidate = _AuthoritativeSnapshot(
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
    ) -> _AuthoritativeSnapshot | None:
        scope_key = self._scope_key()
        exact = self._authoritative_results.get((scope_key, values))
        if exact is not None:
            return _AuthoritativeSnapshot(
                scope_key,
                values,
                _backend_collection_limit(values),
                exact,
            )
        base = self._preview_base
        if base is not None and base.scope_key == scope_key:
            return base
        return None

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
            exact=_snapshot_covers(snapshot, values),
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

    def _show_collection_error(self, error: BaseException | None) -> None:
        message = str(error).strip() if error is not None else "unknown error"
        self.query_one("#commits-timeline", CommitsTimeline).update_result(
            VcsLogResult((), (), (f"Unable to load commits: {message}",))
        )
        self.notify(f"Unable to load commits: {message}", severity="error")

    def _refresh_info(self) -> None:
        if self.is_mounted:
            self.query_one("#commits-info", Static).update(self._build_info())

    def _build_info(self) -> Text:
        worker = self._collection_worker
        return build_commits_info(
            project_display_name=self._project_display_name,
            project_scope=self.project_scope,
            all_projects=self.all_projects,
            include_sdd=self.include_sdd,
            filters=self.filters,
            result=self.result,
            refreshing=worker is not None and worker.is_running,
        )

    def _hints_text(self) -> Text:
        return build_commits_hints(self._registry)

    def _filter_chips(self) -> tuple[str, ...]:
        return commit_filter_chips(self.filters)

    def on_commits_timeline_selection_changed(
        self, event: CommitsTimeline.SelectionChanged
    ) -> None:
        self._selected_commit_index = event.commit_index
        if self._detail_debouncer is None:
            self._render_selected_detail(event.commit_index)
            return
        index = event.commit_index

        def _render() -> None:
            self._render_selected_detail(index)

        self._detail_debouncer.schedule(_render)

    def on_commits_timeline_open_requested(
        self, event: CommitsTimeline.OpenRequested
    ) -> None:
        event.stop()
        self.open_commit(event.commit_index)

    def copy_selected_sha(self) -> None:
        from sase.ace.tui.actions.clipboard import copy_to_system_clipboard

        entry = self._selected_entry()
        if entry is None:
            return
        if copy_to_system_clipboard(entry.commit.full_id):
            self.notify("Copied commit SHA to clipboard")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

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

    def toggle_sdd(self) -> None:
        self.include_sdd = not self.include_sdd
        self._state_changed()

    def toggle_all_projects(self) -> None:
        self.all_projects = not self.all_projects
        self._state_changed()

    def refresh_commits(self) -> None:
        self._schedule_collection()

    def fetch_commits(self) -> None:
        from sase.ace.tui.actions.task_actions import TrackedTaskResult

        spec = self._collection_spec()
        submit = getattr(self.app, "_submit_tracked_task", None)
        if not callable(submit):
            self._schedule_collection()
            return

        def _task() -> TrackedTaskResult[VcsLogResult]:
            try:
                result = self._collect(spec, force_fetch=True)
            except Exception as exc:
                return TrackedTaskResult(
                    success=False,
                    message=f"Commit fetch failed: {exc}",
                    error=str(exc),
                )
            return TrackedTaskResult(
                success=True,
                message="Commit refs fetched",
                payload=result,
            )

        def _complete(completion: TrackedTaskCompletion[VcsLogResult]) -> None:
            if not completion.success or completion.payload is None:
                return
            if spec.generation == self._generation:
                self._apply_result(completion.payload, spec=spec)
            elif self.artifacts_active:
                self._schedule_collection()

        scope = "all" if spec.all_projects else spec.project_scope or "current"
        submit(
            "commit-fetch",
            f"commits:{scope}",
            self._project_file,
            _task,
            display_name=f"Fetch commits ({scope})",
            dedup_key=f"commit-fetch:{scope}",
            duplicate_message="A commit fetch is already running for this scope",
            on_complete=_complete,
            reload_on_complete=False,
        )

    def _selected_entry(self) -> AggregatedCommitWire | None:
        result = self.result
        index = self._selected_commit_index
        if result is None or index is None or not (0 <= index < len(result.commits)):
            return None
        return result.commits[index]

    def open_commit(self, commit_index: int) -> None:
        from sase.ace.tui.modals.commit_view_modal import CommitViewModal

        result = self.result
        if result is None or not (0 <= commit_index < len(result.commits)):
            return
        specs = tuple(self._view_spec(entry) for entry in result.commits)
        self.app.push_screen(CommitViewModal(specs, initial_index=commit_index))

    def open_selected_commit(self) -> None:
        if self._selected_commit_index is not None:
            self.open_commit(self._selected_commit_index)

    def _view_spec(self, entry: AggregatedCommitWire) -> CommitViewSpec:
        return build_commit_view_spec(entry, self.result)

    def _render_selected_detail(self, commit_index: int) -> None:
        result = self.result
        if result is None or not (0 <= commit_index < len(result.commits)):
            return
        if commit_index != self._selected_commit_index:
            return
        entry = result.commits[commit_index]
        key = (entry.repo, entry.commit.full_id)
        if key in self._diff_cache:
            self._update_detail(entry, self._diff_cache[key], loading=False)
            return
        self._update_detail(entry, None, loading=True)
        self._start_diff_load(entry)

    def _start_diff_load(self, entry: AggregatedCommitWire) -> None:
        key = (entry.repo, entry.commit.full_id)
        worker = self._diff_worker
        if worker is not None and worker.is_running:
            if self._diff_loading_key == key:
                return
            worker.cancel()
        spec = self._view_spec(entry)
        self._diff_loading_key = key
        self._diff_worker = self.run_worker(
            lambda key=key, spec=spec: (key, self._diff_loader(spec)),
            thread=True,
            group="artifacts-commit-diff",
            exclusive=True,
            exit_on_error=False,
        )

    def _on_diff_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        self._diff_worker = None
        self._diff_loading_key = None
        if event.state != WorkerState.SUCCESS:
            return
        key, diff_text = cast(tuple[tuple[str, str], str | None], event.worker.result)
        self._diff_cache[key] = diff_text
        entry = self._selected_entry()
        if entry is not None and key == (entry.repo, entry.commit.full_id):
            self._update_detail(entry, diff_text, loading=False)

    def _update_detail(
        self,
        entry: AggregatedCommitWire,
        diff_text: str | None,
        *,
        loading: bool,
    ) -> None:
        if not self.is_mounted:
            return
        self.query_one("#commits-detail", Static).update(
            self._build_detail(entry, diff_text, loading=loading)
        )

    def _build_detail(
        self,
        entry: AggregatedCommitWire,
        diff_text: str | None,
        *,
        loading: bool,
    ) -> RenderableType:
        return build_commit_detail(
            entry,
            diff_text,
            loading=loading,
            result=self.result,
            render_cache=self._syntax_render_cache,
        )

    @staticmethod
    def _cancel_worker(worker: Worker[Any] | None) -> None:
        if worker is not None and worker.is_running:
            worker.cancel()


def _snapshot_breadth(snapshot: _AuthoritativeSnapshot) -> tuple[int, int, int]:
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
    return (-constraints, unlimited, limit)


def _snapshot_covers(
    snapshot: _AuthoritativeSnapshot,
    values: CommitLogFilterValues,
) -> bool:
    if snapshot.filters == values:
        return True
    base = snapshot.filters
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


__all__ = ["CommitCollector", "CommitDiffLoader", "CommitsPane"]
