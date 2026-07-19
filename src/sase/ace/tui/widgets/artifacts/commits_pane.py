"""Composition and lifecycle for the Artifacts commits pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual.worker import Worker

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.vcs_log.models import VcsLogResult

from .commit_filter_bar import CommitFilterBar
from .commits_collection import CommitCollector, CommitsCollectionMixin
from .commits_detail import CommitDiffLoader, CommitsDetailMixin
from .commits_filtering import FILTER_DEBOUNCE_S, CommitsFilteringMixin
from .commits_rendering import (
    build_commits_hints,
    build_commits_info,
    commit_filter_chips,
)
from .commits_timeline import CommitsTimeline
from .panes import ArtifactsPaneLifecycle

if TYPE_CHECKING:
    from sase.ace.tui.actions.task_actions import TrackedTaskCompletion


class CommitsPane(
    CommitsCollectionMixin,
    CommitsFilteringMixin,
    CommitsDetailMixin,
    ArtifactsPaneLifecycle,
    Vertical,
):
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
        self._init_commits_collection(collector)
        self._init_commits_filtering()
        self._init_commits_detail(diff_loader)
        self._registry = load_keymap_registry({})
        self._project_display_name: str | None = None
        self._project_file = ""

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
            delay_s=FILTER_DEBOUNCE_S,
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

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._collection_worker:
            self._on_collection_worker_changed(event)
        elif event.worker is self._diff_worker:
            self._on_diff_worker_changed(event)

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

    @staticmethod
    def _cancel_worker(worker: Worker[Any] | None) -> None:
        if worker is not None and worker.is_running:
            worker.cancel()


__all__ = ["CommitCollector", "CommitDiffLoader", "CommitsPane"]
