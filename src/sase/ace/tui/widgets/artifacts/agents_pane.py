"""Index-backed list and lifecycle for the Artifacts Agent pane.

Mounted on the same :class:`~.snapshot_pane.ArtifactsSnapshotPane` lifecycle
as ``files_pane`` (the closest structural analogue: index-backed,
snapshot-loaded). The ``query`` (sase-tj.5) phase adds a filter bar sibling
module and one compose entry here rather than growing this class body; the
``detail`` phase (sase-tj.6) lands here as grouping, a relation panel, a
lazy detail panel, and link-target resolution.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static
from textual.worker import Worker

from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.core.artifact_relations import RelationIndex
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
)

from ..._artifact_tab_model import ArtifactsPaneContract
from ...relations import build_agents_relation_index
from ...relations._support import relation_index_if_enabled
from .agents_data import (
    AGENTS_FIRST_PAGE_LIMIT,
    AgentsSnapshot,
    load_agents_snapshot,
)
from .agents_detail_panel import AgentsDetailMixin
from .agents_navigation import AgentsNavigationMixin, AgentsOptionList
from .agents_options import AgentsOptionsMixin
from .agents_query import AgentFilterBar, AgentsQueryMixin
from .agents_revival import AgentsRevivalMixin
from .group_fold_navigation import ArtifactGroupFoldMixin
from .relation_panel import RelationPanel, RelationPanelHostMixin
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest


@dataclass(frozen=True, slots=True)
class _AgentsSnapshotResult:
    snapshot: AgentsSnapshot
    query_index: ArtifactQueryIndex | None
    initial_query_result: ArtifactQueryResult | None
    relation_index: RelationIndex | None = None


class ArtifactsAgentsPane(
    AgentsDetailMixin,
    AgentsNavigationMixin,
    AgentsRevivalMixin,
    AgentsOptionsMixin,
    ArtifactGroupFoldMixin,
    RelationPanelHostMixin,
    AgentsQueryMixin,
    ArtifactsSnapshotPane,
):
    """Browse the durable agent catalog without blocking the event loop."""

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
        self._init_agents_query()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._extension_generation = 0
        self._init_agents_navigation()
        self._init_agents_detail()
        self._init_group_fold()
        self._init_agents_revival()

    def compose(self) -> ComposeResult:
        yield AgentFilterBar(id="agent-filter-bar", profile=self._query_profile)
        yield Static(
            self._scope_text(),
            id="agents-info",
            classes="artifacts-pane-info",
        )
        with Horizontal(id="agents-panels"):
            list_panel = Vertical(id="agents-list-panel")
            list_panel.border_title = "Agent"
            with list_panel:
                yield Static("No agents found.", id="agents-empty")
                yield Static(self._status_text(), id="agents-status")
                yield AgentsOptionList(id="agents-list")
                yield RelationPanel(
                    id="agents-relation-panel",
                    classes="artifacts-relation-panel",
                )
            detail_panel = Vertical(id="agents-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="agents-detail-scroll"):
                    yield Static(
                        "Select an agent to see its details.",
                        id="agents-detail",
                    )
        yield Static(self._hints_text(), id="agents-hints")

    def on_mount(self) -> None:
        self._start_detail_debouncer()
        self._refresh_options()

    def on_unmount(self) -> None:
        self._extension_generation += 1
        self._cancel_detail_debouncer()
        cancel_pump_free_tasks(self)
        self._cancel_detail_worker()
        self._cancel_agents_query_workers()
        self._cancel_snapshot_worker()

    def on_deactivate(self) -> None:
        self._cancel_detail_debouncer()

    def on_first_activate(self) -> None:
        self._request_load(force=False, full=False)

    def on_activate(self) -> None:
        self.focus_list()
        if not self._loading and self._current_snapshot() is None:
            self._request_load(force=False, full=False)

    def on_refresh(self) -> None:
        self._request_load(force=True, full=False)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active registry for pane-scoped key hints."""

        self._registry = registry
        self._update_static("#agents-info", self._scope_text())
        self._update_static("#agents-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope and reload for it."""

        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#agents-info", self._scope_text())
        if not changed:
            return
        self.clear_pending_entry_target()
        self._extension_generation += 1
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False, full=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> AgentsSnapshot | None:
        return self._snapshot

    def _request_load(self, *, force: bool, full: bool = False) -> None:
        self._request_snapshot(force=force, full=full)

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        del request
        self._update_status()

    def _build_snapshot(self, request: SnapshotRequest) -> _AgentsSnapshotResult:
        snapshot = load_agents_snapshot(
            request.project,
            None if request.full else AGENTS_FIRST_PAGE_LIMIT,
        )
        query_index = (
            self._build_agents_query_index(snapshot, generation=request.generation)
            if request.full
            else None
        )
        return _AgentsSnapshotResult(
            snapshot=snapshot,
            relation_index=relation_index_if_enabled(
                self.contract,
                lambda contract: build_agents_relation_index(
                    snapshot, contract=contract
                ),
            ),
            query_index=query_index,
            initial_query_result=(
                None
                if query_index is None
                else self._initial_agents_query_result(query_index)
            ),
        )

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return (
            isinstance(result, _AgentsSnapshotResult)
            and request.generation == self._load_generation
            and result.snapshot.project == self.project_scope
            and (
                result.query_index is None
                or result.query_index.generation == request.generation
            )
        )

    def _apply_snapshot(self, result: Any, request: SnapshotRequest) -> None:
        preferred = self.selected_entry_target()
        self._query_session.clear()
        self._snapshot = result.snapshot
        self._relation_index = result.relation_index
        self._invalidate_detail_cache()
        self._query_index = result.query_index
        if result.initial_query_result is not None:
            self._query_session.remember(result.initial_query_result)
        self._load_error = None
        self._set_agent_filter_completion_sources()
        self._refresh_options(preferred_target=preferred)
        if (
            not request.full
            and not result.snapshot.complete
            and self._load_error is None
        ):
            self._schedule_full_extension(request.generation)

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error
        self._update_status()

    def _handle_auxiliary_worker(self, event: Worker.StateChanged) -> bool:
        if event.worker is self._detail_worker:
            self._on_detail_worker_changed(event)
            return True
        return self._handle_agents_query_worker(event)

    def _schedule_full_extension(self, generation: int) -> None:
        """Yield first paint, then request the unbounded index extension."""

        self._extension_generation += 1
        extension_generation = self._extension_generation

        async def extend() -> None:
            await asyncio.sleep(0)
            if (
                extension_generation != self._extension_generation
                or generation != self._load_generation
                or not self.artifacts_active
            ):
                return
            self._request_load(force=False, full=True)

        spawn_pump_free_task(
            self,
            extend(),
            name="sase-artifacts-agents-full-extension",
            registry_attr="_agents_extension_tasks",
        )

    @on(OptionList.OptionHighlighted, "#agents-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        self._update_static("#agents-hints", self._hints_text())
        self._schedule_detail()

    @on(OptionList.OptionSelected, "#agents-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()


__all__ = ["ArtifactsAgentsPane"]
