"""Composition and lifecycle for the Artifacts Stitches pane."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Static
from textual.worker import Worker

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.project_display_names import ProjectRefDisplaySnapshot
from sase.vcs_provider._types import MergeVisibility
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.filter_query import CommitLogFilterValues, to_query_string

from ....link_reveal import active_pane_link_reveal, pane_canonical_query
from ...models.artifact_groups import ArtifactGroupBuildResult, build_grouped_rows
from ...models.group_fold import GroupFoldRegistry
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
from .commits_timeline import (
    STITCHES_PANE_ID,
    CommitsTimeline,
    commit_group_label,
    commit_key_value,
    commit_row_target,
)
from .entry_navigation import ArtifactEntryTarget
from .group_fold_navigation import ArtifactGroupFoldMixin
from .panes import ArtifactsPaneLifecycle
from .query_session import ArtifactQuerySession
from .relation_panel import RelationPanel, RelationPanelHostMixin
from .shell import build_reveal_chip
from .types import ARTIFACTS_ACCENTS

STITCHES_DETAIL_DEBOUNCE_S = 0.25


class CommitsPane(
    ArtifactGroupFoldMixin,
    CommitsCollectionMixin,
    CommitsFilteringMixin,
    CommitsDetailMixin,
    RelationPanelHostMixin,
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
        self._init_group_fold()

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
                yield RelationPanel(
                    id="stitches-relation-panel",
                    classes="artifacts-relation-panel",
                )
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
            try:
                header = self.query_one("#stitches-info-header", Static)
                legend = self.query_one("#stitches-legend", Static)
            except NoMatches:
                return
            header.update(self._build_info_header())
            legend.update(self._build_legend())
            self._refresh_position_badge()

    def _refresh_position_badge(self) -> None:
        """Refresh only the selection-dependent Stitches chrome."""
        if self.is_mounted:
            try:
                position = self.query_one("#stitches-position", Static)
            except NoMatches:
                return
            position.update(self._build_position_badge())

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
        text = build_commits_info_header(
            refreshing=worker is not None and worker.is_running,
            has_content=self.result is not None,
            active_limit=self._active_limit(),
        )
        reveal = active_pane_link_reveal(
            self._registry.app,
            STITCHES_PANE_ID,
            current_canonical=pane_canonical_query(self),
        )
        if reveal is not None:
            text.append("\n")
            text.append_text(
                build_reveal_chip(
                    label=f"Revealed {reveal.ref}",
                    accent=self._accent(),
                    return_hint=key_display_name(self._registry.app.prev_query),
                )
            )
        return text

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
        return build_commits_hints(self._registry, accent=self._accent())

    def _accent(self) -> str:
        contract = self.contract
        return ARTIFACTS_ACCENTS["stitches"] if contract is None else contract.accent

    def _group_pane_id(self) -> str:
        return STITCHES_PANE_ID

    def _sync_timeline_grouping(self, timeline: CommitsTimeline) -> None:
        mode = self._active_grouping_mode()
        registry = self._group_fold_registry() if mode is not None else None
        timeline.set_grouping(mode=mode, fold_registry=registry, accent=self._accent())

    def _group_build_result(
        self,
        *,
        fold_registry: GroupFoldRegistry,
    ) -> ArtifactGroupBuildResult[Any]:
        mode = self._active_grouping_mode()
        if mode is None or self.result is None:
            return ArtifactGroupBuildResult(rows=(), known_group_keys=())
        return build_grouped_rows(
            self.result.commits,
            pane_id=STITCHES_PANE_ID,
            mode_id=mode.id,
            keys=(mode.id,),
            key_values=lambda entry: (commit_key_value(entry, mode.id),),
            label_for=lambda _level, value: commit_group_label(mode.id, value),
            target_for=commit_row_target,
            fold_registry=fold_registry,
        )

    def _group_refresh(self, preferred_target: ArtifactEntryTarget | None) -> None:
        if self.result is None:
            return
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        self._sync_timeline_grouping(timeline)
        timeline._rebuild_options(self.result, selected_target=preferred_target)
        self._selected_commit_index = timeline.selected_commit_index
        self._refresh_info()
        self._refresh_position_badge()

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

    def fetch_commits(self) -> None:
        self._schedule_collection(force_fetch=True)

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
