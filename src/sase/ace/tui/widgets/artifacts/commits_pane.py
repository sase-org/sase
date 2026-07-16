"""State and worker orchestration for the Artifacts commits pane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
from sase.vcs_log.models import VcsLogResult

from .commit_filters import CommitLogFilterValues
from .commits_rendering import (
    build_commit_detail,
    build_commit_view_spec,
    build_commits_hints,
    build_commits_info,
    commit_filter_chips,
)
from .commits_timeline import CommitsTimeline
from .panes import ArtifactsPaneLifecycle

if TYPE_CHECKING:
    from sase.ace.tui.actions.task_actions import TrackedTaskCompletion

CommitCollector = Callable[..., VcsLogResult]
CommitDiffLoader = Callable[[CommitViewSpec], str | None]


@dataclass(frozen=True)
class _CollectionSpec:
    generation: int
    project_scope: str | None
    all_projects: bool
    include_sdd: bool
    filters: CommitLogFilterValues


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
        self._collection_pending = False
        self._selected_commit_index: int | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._diff_worker: Worker[tuple[tuple[str, str], str | None]] | None = None
        self._diff_cache: dict[tuple[str, str], str | None] = {}
        self._diff_loading_key: tuple[str, str] | None = None
        self._syntax_render_cache = LazySyntaxRenderCache()

    def compose(self) -> ComposeResult:
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

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
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
        self._generation += 1
        if self.artifacts_active:
            self._schedule_collection()

    def _collection_spec(self) -> _CollectionSpec:
        return _CollectionSpec(
            generation=self._generation,
            project_scope=self.project_scope,
            all_projects=self.all_projects,
            include_sdd=self.include_sdd,
            filters=self.filters,
        )

    def _collect(self, spec: _CollectionSpec, *, force_fetch: bool) -> VcsLogResult:
        return self._collector(
            cwd=os.getcwd(),
            limit=spec.filters.limit,
            filters=spec.filters.backend_filters(),
            repo_filters=spec.filters.repos,
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
        self._collection_worker = None
        self._collection_generation = None
        stale = generation != self._generation
        pending = self._collection_pending or stale
        if event.state == WorkerState.SUCCESS and not pending:
            self._apply_result(cast(VcsLogResult, event.worker.result))
        elif event.state == WorkerState.ERROR and not pending:
            self._show_collection_error(event.worker.error)

        self._collection_pending = False
        self._refresh_info()
        if pending and self.artifacts_active:
            self._schedule_collection()

    def _apply_result(self, result: VcsLogResult) -> None:
        self.result = result
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        self._selected_commit_index = timeline.update_result(result)
        self._refresh_info()
        if self._selected_commit_index is not None:
            self._render_selected_detail(self._selected_commit_index)

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
        from sase.ace.tui.modals.commit_filters_modal import CommitFiltersModal

        repo_names = (
            tuple(repo.name for repo in self.result.repos)
            if self.result is not None
            else ()
        )

        def _apply(values: CommitLogFilterValues | None) -> None:
            if values is None or values == self.filters:
                return
            self.filters = values
            self._state_changed()

        self.app.push_screen(CommitFiltersModal(self.filters, repo_names), _apply)

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
                self._apply_result(completion.payload)
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


__all__ = ["CommitCollector", "CommitDiffLoader", "CommitsPane"]
