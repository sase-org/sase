"""Composition and off-thread lifecycle for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.bead.filter_query import to_query_string
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)

from sase.core.artifact_relations import RelationIndex

from ..._artifact_tab_model import ArtifactsPaneContract
from ...relations import build_beads_relation_index
from ...relations._support import relation_index_if_enabled
from .bead_filter_bar import BeadFilterBar
from .beads_data import BeadsSnapshot, load_beads_snapshot
from .beads_data_models import ExternalIssueLink, ExternalIssueProjectCache
from .beads_filtering import BeadFilterIndex
from .beads_filter_session import BeadsFilterSessionMixin
from .beads_list import BeadRow
from .beads_navigation import BeadsNavigationMixin, BeadsOptionList
from .beads_options import BeadsOptionsMixin
from .query_rows import build_beads_query_index
from .query_session import ArtifactQuerySession
from .relation_panel import RelationPanel, RelationPanelHostMixin
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest

if TYPE_CHECKING:
    from ...app import AceApp


@dataclass(frozen=True, slots=True)
class _BeadsSnapshotResult:
    snapshot: BeadsSnapshot
    filter_index: BeadFilterIndex
    query_index: ArtifactQueryIndex
    initial_query_result: ArtifactQueryResult | None
    relation_index: RelationIndex | None = None


class ArtifactsBeadsPane(
    BeadsFilterSessionMixin,
    BeadsNavigationMixin,
    BeadsOptionsMixin,
    RelationPanelHostMixin,
    ArtifactsSnapshotPane,
):
    """Browse task beads and expandable epic phase trees."""

    can_focus = False

    def __init__(
        self,
        *,
        contract: ArtifactsPaneContract | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_snapshot_lifecycle()
        self.contract = contract
        profile = (
            contract.query_profile
            if contract is not None
            else compiled_profile_for_builtin_pane("beads")
        )
        assert profile is not None
        self._query_profile = profile
        self._query_index: ArtifactQueryIndex | None = None
        self._query_session = ArtifactQuerySession(
            self,
            group="artifacts-beads-query",
            on_current_result=lambda _result: self._refresh_options(),
        )
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._init_beads_navigation()
        self._init_beads_filter_session()
        self._init_beads_options()

    def compose(self) -> ComposeResult:
        yield BeadFilterBar(id="bead-filter-bar", profile=self._query_profile)
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="beads-info")
        with Horizontal(id="beads-panels"):
            list_panel = Vertical(id="beads-list-panel")
            list_panel.border_title = "Beads"
            with list_panel:
                yield Static(self._status_text(), id="beads-status")
                yield BeadsOptionList(id="beads-list")
                yield RelationPanel(
                    id="beads-relation-panel",
                    classes="artifacts-relation-panel",
                )
            detail_panel = Vertical(id="beads-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="beads-detail-scroll"):
                    yield Static("", id="beads-detail-properties")
                    yield Markdown(self._empty_detail(), id="beads-detail")
        yield Static(self._hints_text(), id="beads-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._query_session.clear()
        self._cancel_snapshot_worker()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        self._request_load(force=False)

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_refresh(self) -> None:
        self._request_load(force=True)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        self._update_static("#beads-info", self._scope_text())
        self._update_static("#beads-hints", self._hints_text())
        self._update_detail()

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#beads-info", self._scope_text())
        if not changed:
            return
        self.clear_pending_entry_target()
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> BeadsSnapshot | None:
        return self._snapshot

    def _snapshot_matches_scope(self) -> bool:
        return (
            self._snapshot is not None and self._snapshot.project == self.project_scope
        )

    def _snapshot_row_count(self) -> int:
        snapshot = self._snapshot
        return 0 if snapshot is None else len(snapshot.tasks) + len(snapshot.epics)

    def external_links_for_row(self, row: BeadRow) -> tuple[ExternalIssueLink, ...]:
        """Return cached external issue links for *row*."""

        if self._snapshot is None:
            return ()
        return self._snapshot.external_links.get((row.project, row.issue.id), ())

    def external_project_cache(
        self,
        project: str,
    ) -> ExternalIssueProjectCache | None:
        """Return cached issue-provider state for *project*."""

        if self._snapshot is None:
            return None
        return self._snapshot.external_projects.get(project)

    def _request_load(self, *, force: bool) -> None:
        self._request_snapshot(force=force)

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        del request
        self._update_static("#beads-status", self._status_text())

    def _build_snapshot(self, request: SnapshotRequest) -> _BeadsSnapshotResult:
        snapshot = load_beads_snapshot(
            request.project,
            previous=self._snapshot,
            force=request.force,
            patches=tuple(getattr(self.app, "patches", ())),
        )
        filter_index, query_index = build_beads_query_index(
            snapshot,
            pane_id=self._query_profile.pane_id,
            generation=request.generation,
            profile=self._query_profile,
        )
        initial_query = to_query_string(self.filters)
        initial_result = (
            None
            if not initial_query
            else evaluate_artifact_query_many(initial_query, query_index)
        )
        return _BeadsSnapshotResult(
            snapshot=snapshot,
            filter_index=filter_index,
            query_index=query_index,
            initial_query_result=initial_result,
            relation_index=relation_index_if_enabled(
                self.contract,
                lambda contract: build_beads_relation_index(
                    snapshot, contract=contract
                ),
            ),
        )

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return (
            isinstance(result, _BeadsSnapshotResult)
            and result.snapshot.project == request.project
            and result.query_index.generation == request.generation
        )

    def _apply_snapshot(self, result: Any, request: SnapshotRequest) -> None:
        del request
        preferred = self._selected_option_id()
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("beads")
        self._query_session.clear()
        self._snapshot = result.snapshot
        self._relation_index = result.relation_index
        self._filter_index = result.filter_index
        self._filter_index_source_key = result.snapshot.source_key
        self._query_index = result.query_index
        if result.initial_query_result is not None:
            self._query_session.remember(result.initial_query_result)
        self._load_error = None
        if self._filter_session_open:
            self._set_filter_completion_sources()
        self._refresh_options(preferred_id=preferred)

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error
        self._update_static("#beads-status", self._status_text())
        self._update_detail()

    def _handle_auxiliary_worker(self, event: Worker.StateChanged) -> bool:
        return self._query_session.handle_worker_state_changed(event)

    @on(OptionList.OptionHighlighted, "#beads-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)
        self._sync_artifacts_footer()

    @on(OptionList.OptionSelected, "#beads-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast("AceApp", self.app).action_beads_view_selected()


__all__ = ["ArtifactsBeadsPane", "BeadRow"]
