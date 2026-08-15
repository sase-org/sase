"""Composition and lifecycle for the Artifacts Stitches pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual.worker import Worker

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.project_display_names import ProjectRefDisplaySnapshot
from sase.vcs_provider._types import MergeVisibility
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.filter_query import CommitLogFilterValues, to_query_string

from .commit_filter_bar import CommitFilterBar
from .commits_collection import (
    CommitCollectionPayload,
    CommitCollector,
    CommitsCollectionMixin,
    snapshot_covers,
)
from .commits_detail import CommitDiffLoader, CommitsDetailMixin
from .commits_filtering import FILTER_DEBOUNCE_S, CommitsFilteringMixin
from .commits_rendering import (
    build_commit_position_badge,
    build_commits_hints,
    build_commits_info,
    build_commits_info_header,
    build_commits_legend,
    commit_filter_chips,
)
from .commits_timeline import CommitsTimeline
from .panes import ArtifactsPaneLifecycle
from .query_session import ArtifactQuerySession
from .types import ARTIFACTS_ACCENTS

if TYPE_CHECKING:
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion


STITCHES_DETAIL_DEBOUNCE_S = 0.25


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
        initial_filters: CommitLogFilterValues | None = None,
        contract: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.contract = contract
        profile = (
            contract.query_profile
            if contract is not None
            else compiled_profile_for_builtin_pane("stitches")
        )
        assert profile is not None
        self._query_profile = profile
        self._query_session = ArtifactQuerySession(
            self,
            group="artifacts-stitches-query",
            on_current_result=lambda _result: self._refresh_query_result(),
        )
        self._init_commits_collection(collector, initial_filters=initial_filters)
        self._init_commits_filtering()
        self._init_commits_detail(diff_loader)
        self._registry = load_keymap_registry({})
        self._last_project_scope = self.filters.project
        self._project_files: dict[str, str] = {}
        self._project_ref_display = ProjectRefDisplaySnapshot()

    def compose(self) -> ComposeResult:
        yield CommitFilterBar(id="commit-filter-bar", profile=self._query_profile)
        with Vertical(id="stitches-info"):
            yield Static(self._build_info_header(), id="stitches-info-header")
            with Horizontal(id="stitches-legend-row"):
                yield Static(
                    self._build_position_badge(),
                    id="stitches-position",
                )
                yield Static(self._build_legend(), id="stitches-legend")
        with Horizontal(id="stitches-main"):
            with Vertical(id="stitches-list-container"):
                timeline = CommitsTimeline(id="stitches-timeline")
                timeline.set_selection_callback(self._sync_timeline_selection)
                yield timeline
                yield Static(self._hints_text(), id="stitches-footer")
            with Vertical(id="stitches-detail-container"):
                with VerticalScroll(id="stitches-detail-scroll"):
                    yield Static(
                        Text(
                            "Select a commit to inspect its message and diff.",
                            style="dim italic",
                        ),
                        id="stitches-detail",
                    )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(
            self.app,
            delay_s=STITCHES_DETAIL_DEBOUNCE_S,
        )
        self._filter_debouncer = DetailPanelDebouncer(
            self.app,
            delay_s=FILTER_DEBOUNCE_S,
        )
        bar = self.query_one(CommitFilterBar)
        bar.set_query(to_query_string(self.filters))
        bar.set_status(
            None,
            exact=False,
            error=None,
            coverage_label="loads lazily",
        )

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._filter_debouncer is not None:
            self._filter_debouncer.cancel()
        self._query_session.clear()
        self._cancel_worker(self._collection_worker)
        self._cancel_worker(self._diff_worker)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use configured Stitches actions in the pane's hint bar."""
        self._registry = registry
        if self.is_mounted:
            self.query_one("#stitches-footer", Static).update(self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
        project_file: str | None = None,
    ) -> None:
        """Replace the query-owned project facet from a scope selection."""
        visible_ref = (display_name or project) if project is not None else None
        if visible_ref is not None:
            self._last_project_scope = visible_ref
            if project_file:
                self._project_files[visible_ref] = project_file
        if visible_ref == self.filters.project:
            return
        values = replace(self.filters, project=visible_ref)
        if self.is_mounted:
            self._commit_filter_values(values, close_session=False)
        else:
            self.filters = values

    def set_project_completion_sources(
        self,
        projects: tuple[str, ...],
        *,
        project_files: dict[str, str] | None = None,
        project_ref_display: ProjectRefDisplaySnapshot | None = None,
    ) -> None:
        """Warm project completions and fetch metadata from loaded inventory."""
        if project_files:
            self._project_files.update(project_files)
        if project_ref_display is not None:
            self._project_ref_display = project_ref_display
        if self.is_mounted:
            self.query_one(CommitFilterBar).set_project_completion_sources(projects)

    def on_activate(self) -> None:
        if self.is_mounted:
            timeline = self.query_one("#stitches-timeline", CommitsTimeline)
            timeline.focus()
            timeline.prewarm_render_cache()
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
        elif self._query_session.handle_worker_state_changed(event):
            return

    def _refresh_info(self) -> None:
        if self.is_mounted:
            self.query_one("#stitches-info-header", Static).update(
                self._build_info_header()
            )
            self.query_one("#stitches-legend", Static).update(self._build_legend())
            self._refresh_position_badge()

    def _refresh_position_badge(self) -> None:
        """Refresh only the selection-dependent Stitches chrome."""
        if self.is_mounted:
            self.query_one("#stitches-position", Static).update(
                self._build_position_badge()
            )

    def _active_limit(self) -> int | None:
        result = self.result
        if result is None or not result.potentially_truncated:
            return None
        values = (
            self._live_filter_values
            if self._filter_session_open and self._live_filter_values is not None
            else self.filters
        )
        return values.limit or None

    def _build_info_header(self) -> Text:
        worker = self._collection_worker
        return build_commits_info_header(
            refreshing=worker is not None and worker.is_running,
            has_content=self.result is not None,
            active_limit=self._active_limit(),
        )

    def _build_position_badge(self) -> Text:
        return build_commit_position_badge(
            result=self.result,
            selected_commit_index=self._selected_commit_index,
        )

    def _build_legend(self) -> Text:
        return build_commits_legend(self.result)

    def _build_info(self) -> Text:
        worker = self._collection_worker
        return build_commits_info(
            result=self.result,
            refreshing=worker is not None and worker.is_running,
            active_limit=self._active_limit(),
            selected_commit_index=self._selected_commit_index,
        )

    def _hints_text(self) -> Text:
        contract = self.contract
        accent = ARTIFACTS_ACCENTS["stitches"] if contract is None else contract.accent
        return build_commits_hints(self._registry, accent=accent)

    def _filter_chips(self) -> tuple[str, ...]:
        return commit_filter_chips(self.filters)

    def _refresh_query_result(self) -> None:
        values = (
            self._live_filter_values
            if self._filter_session_open and self._live_filter_values is not None
            else self.filters
        )
        snapshot = self._authoritative_snapshot(values)
        if snapshot is None:
            return
        displayed = self._filtered_result(
            snapshot.result,
            values,
            resolve_fresh_bounds=True,
        )
        self._display_result(displayed, live_preview=self._filter_session_open)
        self._set_result_status(
            displayed,
            exact=snapshot_covers(snapshot, values) and not self._query_result_pending,
            values=values,
        )

    def toggle_sdd(self) -> None:
        self._commit_filter_values(
            replace(self.filters, sidecar=not self.filters.sidecar),
            close_session=False,
        )

    def cycle_merges(self) -> None:
        mode = _next_merge_visibility(self.filters.merges)
        self._commit_filter_values(
            replace(self.filters, merges=mode),
            close_session=False,
        )
        self.notify(f"Merge commits: {mode}", timeout=3)

    def toggle_all_projects(self) -> None:
        project = self.filters.project
        if project is not None:
            self._last_project_scope = project
            self._commit_filter_values(
                replace(self.filters, project=None),
                close_session=False,
            )
            return
        if self._last_project_scope is None:
            self.notify("No project to restore; press p to pick one.", timeout=3)
            return
        self._commit_filter_values(
            replace(self.filters, project=self._last_project_scope),
            close_session=False,
        )

    def refresh_commits(self) -> None:
        self._schedule_collection()

    def fetch_commits(self) -> None:
        from sase.ace.tui.actions.proc_actions import TrackedProcResult

        spec = self._collection_spec()
        submit = getattr(self.app, "_submit_tracked_proc", None)
        if not callable(submit):
            self._schedule_collection()
            return

        def _proc() -> TrackedProcResult[CommitCollectionPayload]:
            try:
                result = self._collect_payload(spec, force_fetch=True)
            except Exception as exc:
                return TrackedProcResult(
                    success=False,
                    message=f"Commit fetch failed: {exc}",
                    error=str(exc),
                )
            return TrackedProcResult(
                success=True,
                message="Commit refs fetched",
                payload=result,
            )

        def _complete(
            completion: TrackedProcCompletion[CommitCollectionPayload],
        ) -> None:
            if not completion.success or completion.payload is None:
                return
            if spec.generation == self._generation:
                self._apply_result(
                    completion.payload.result,
                    spec=spec,
                    query_index=completion.payload.query_index,
                    initial_query_result=completion.payload.initial_query_result,
                )
            elif self.artifacts_active:
                self._schedule_collection()

        scope = spec.project_scope or "all"
        project_file = (
            self._project_files.get(spec.project_scope, "")
            if spec.project_scope is not None
            else ""
        )
        submit(
            "commit-fetch",
            f"commits:{scope}",
            project_file,
            _proc,
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


def _next_merge_visibility(current: MergeVisibility) -> MergeVisibility:
    if current == "hide":
        return "show"
    if current == "show":
        return "only"
    return "hide"


__all__ = ["CommitCollector", "CommitDiffLoader", "CommitsPane"]
