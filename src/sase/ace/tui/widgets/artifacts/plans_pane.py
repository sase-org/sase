"""Composition and lifecycle for the Artifacts plans pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)
from sase.core.artifact_relations import RelationIndex
from sase.plan_search.filter_query import to_query_string

from ..._artifact_tab_model import ArtifactsPaneContract
from ...relations import (
    build_documents_relation_index,
    build_provider_relation_index,
)
from ...relations._support import relation_index_if_enabled
from .plan_filter_bar import PlanFilterBar
from .plans_data import PlansSnapshot, load_plans_snapshot
from .plans_deep_archive import DEEP_ARCHIVE_DEBOUNCE_S
from .plans_filtering import PlanFilterIndex
from .plans_filter_session import PlansFilterSessionMixin
from .plans_list import PlanRow, build_plan_options
from .plans_navigation import PlansNavigationMixin, PlansOptionList
from .plans_options import PlansOptionsMixin
from .group_fold_navigation import ArtifactGroupFoldMixin
from .query_rows import build_plans_query_index
from .query_session import ArtifactQuerySession
from .relation_panel import RelationPanel, RelationPanelHostMixin
from .plans_rendering import (
    active_plan_text,
    archive_text,
    project_badge,
    proposal_text,
)
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest

if TYPE_CHECKING:
    from ...app import AceApp


# Preserve the rendering seams exposed by the original plans_pane module.
_proposal_text = proposal_text
_active_plan_text = active_plan_text
_archive_text = archive_text
_project_badge = project_badge


@dataclass(frozen=True, slots=True)
class _PlansSnapshotResult:
    snapshot: PlansSnapshot
    filter_index: PlanFilterIndex
    query_index: ArtifactQueryIndex
    initial_query_result: ArtifactQueryResult | None
    relation_index: RelationIndex | None = None


class ArtifactsDocumentsPane(
    ArtifactGroupFoldMixin,
    PlansFilterSessionMixin,
    PlansNavigationMixin,
    PlansOptionsMixin,
    RelationPanelHostMixin,
    ArtifactsSnapshotPane,
):
    """Browse provider-backed markdown documents."""

    can_focus = False

    def __init__(
        self,
        *,
        contract: ArtifactsPaneContract | None = None,
        provider_kind: str = "plan",
        provider_label: str = "Plan",
        pane_key: str = "ref:plan",
        provider_spec: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_snapshot_lifecycle()
        self.contract = contract
        if contract is not None:
            provider_kind = contract.ref_kind or provider_kind
            provider_label = contract.label
            pane_key = contract.id
            if contract.facts.source == "provider":
                provider_spec = provider_spec
        self.provider_kind = provider_kind
        self.provider_label = provider_label
        self.pane_key = pane_key
        self.provider_spec = provider_spec or {}
        profile = (
            contract.query_profile
            if contract is not None
            else compiled_profile_for_builtin_pane("ref:plan")
        )
        assert profile is not None
        self._query_profile = profile
        self._query_index: ArtifactQueryIndex | None = None
        self._query_session = ArtifactQuerySession(
            self,
            group=f"artifacts-{pane_key}-query",
            on_current_result=lambda _result: self._refresh_options(),
        )
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._init_plans_navigation()
        self._init_plans_filter_session()
        self._init_plans_options()
        self._init_group_fold()

    def compose(self) -> ComposeResult:
        accent = None if self.contract is None else self.contract.accent
        yield PlanFilterBar(
            id="plan-filter-bar",
            accent=accent,
            profile=self._query_profile,
        )
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="plans-info")
        with Horizontal(id="plans-panels"):
            list_panel = Vertical(id="plans-list-panel")
            list_panel.border_title = (
                "Plan pipeline" if self.provider_kind == "plan" else self.provider_label
            )
            with list_panel:
                yield Static(self._status_text(), id="plans-status")
                yield PlansOptionList(id="plans-list")
                yield RelationPanel(
                    id="plans-relation-panel",
                    classes="artifacts-relation-panel",
                )
            detail_panel = Vertical(id="plans-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="plans-detail-scroll"):
                    yield Static("", id="plans-detail-properties")
                    yield Markdown(self._empty_detail(), id="plans-detail")
        yield Static(self._hints_text(), id="plans-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._deep_archive_debouncer = DetailPanelDebouncer(
            self.app,
            delay_s=DEEP_ARCHIVE_DEBOUNCE_S,
        )
        self._refresh_options()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._deep_archive_debouncer is not None:
            self._deep_archive_debouncer.cancel()
        self._cancel_snapshot_worker()
        if (
            self._deep_archive_worker is not None
            and not self._deep_archive_worker.is_finished
        ):
            self._deep_archive_worker.cancel()
        self._query_session.clear()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if self._snapshot is None or self._snapshot.project != self.project_scope:
            self._request_load(force=False)
        else:
            self._schedule_deep_archive(self._display_filter_values())

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._invalidate_deep_archive_request()

    def on_refresh(self) -> None:
        self._request_load(force=True)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        self._update_static("#plans-info", self._scope_text())
        self._update_static("#plans-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#plans-info", self._scope_text())
        if not changed:
            return
        self.clear_pending_entry_target()
        self._load_error = None
        self._reset_deep_archive_state()
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> PlansSnapshot | None:
        return self._snapshot

    def _snapshot_matches_scope(self) -> bool:
        return (
            self._snapshot is not None and self._snapshot.project == self.project_scope
        )

    def _snapshot_row_count(self) -> int:
        snapshot = self._snapshot
        if snapshot is None:
            return 0
        return len(snapshot.proposals) + len(snapshot.active) + len(snapshot.archive)

    def _request_load(self, *, force: bool) -> None:
        self._request_snapshot(force=force)

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        del request
        self._update_status()

    def _build_snapshot(self, request: SnapshotRequest) -> _PlansSnapshotResult:
        previous = (
            self._snapshot
            if self._snapshot is not None and self._snapshot.project == request.project
            else None
        )
        snapshot = load_plans_snapshot(
            request.project,
            provider_kind=self.provider_kind,
            provider_label=self.provider_label,
            provider_presentation=(
                self.contract.presentation if self.contract is not None else None
            ),
            provider_presentation_digest=(
                self.contract.presentation_digest if self.contract is not None else ""
            ),
            previous=previous,
            force=request.force,
        )
        filter_index, query_index = build_plans_query_index(
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
        return _PlansSnapshotResult(
            snapshot=snapshot,
            filter_index=filter_index,
            query_index=query_index,
            initial_query_result=initial_result,
            relation_index=relation_index_if_enabled(
                self.contract,
                lambda contract: (
                    build_documents_relation_index(snapshot, contract=contract)
                    if contract.facts.is_plan_adapter
                    else build_provider_relation_index(snapshot, contract=contract)
                ),
            ),
        )

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return (
            isinstance(result, _PlansSnapshotResult)
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
            cancel_jump(self.pane_key)
        snapshot_changed = result.snapshot is not self._snapshot
        self._query_session.clear()
        self._snapshot = result.snapshot
        if self.project_scope is not None and self._project_display_name is None:
            display_name = result.snapshot.display_names.get(self.project_scope)
            if display_name is not None:
                self._project_display_name = display_name
                self._update_static("#plans-info", self._scope_text())
        self._relation_index = result.relation_index
        self._filter_index = result.filter_index
        self._filter_index_snapshot = result.snapshot
        self._query_index = result.query_index
        if result.initial_query_result is not None:
            self._query_session.remember(result.initial_query_result)
        if snapshot_changed:
            self._reset_deep_archive_state()
        self._load_error = None
        if self._filter_session_open:
            self._set_filter_completion_sources()
        self._refresh_options(preferred_id=preferred)
        self._schedule_deep_archive(self._display_filter_values())

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error
        self._update_status()

    def _handle_auxiliary_worker(self, event: Worker.StateChanged) -> bool:
        if self._query_session.handle_worker_state_changed(event):
            return True
        if event.worker is self._deep_archive_worker:
            self._on_deep_archive_worker_changed(event)
            return True
        return False

    @on(OptionList.OptionHighlighted, "#plans-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)
        self._sync_artifacts_footer()

    @on(OptionList.OptionSelected, "#plans-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        payload = self.selected_preview()
        if payload is None:
            return
        from ...modals.preview_panel_modal import PreviewPanelModal

        self.app.push_screen(PreviewPanelModal(payload))


class ArtifactsPlansPane(ArtifactsDocumentsPane):
    """Compatibility name for the provider-backed plan documents pane."""


__all__ = ["ArtifactsDocumentsPane", "ArtifactsPlansPane", "PlanRow"]
