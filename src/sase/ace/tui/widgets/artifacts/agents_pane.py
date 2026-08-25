"""Index-backed list and lifecycle for the Artifacts Agent pane.

Mounted on the same :class:`~.snapshot_pane.ArtifactsSnapshotPane` lifecycle
as ``files_pane`` (the closest structural analogue: index-backed,
snapshot-loaded), kept intentionally thin. The ``query`` (sase-tj.5),
``detail`` (sase-tj.6), and ``revive`` (sase-tj.7) phases each add their own
sibling module and one base-class/compose entry here — a filter bar, a
detail panel and relation panel, and a revive binding, respectively — rather
than growing this class body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry

from ..._artifact_tab_model import ArtifactsPaneContract
from .agents_data import AgentsSnapshot, load_agents_snapshot
from .agents_navigation import AgentsNavigationMixin, AgentsOptionList
from .agents_options import AgentsOptionsMixin
from .snapshot_pane import ArtifactsSnapshotPane, SnapshotRequest


@dataclass(frozen=True, slots=True)
class _AgentsSnapshotResult:
    snapshot: AgentsSnapshot


class ArtifactsAgentsPane(
    AgentsNavigationMixin,
    AgentsOptionsMixin,
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
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._init_agents_navigation()

    def compose(self) -> ComposeResult:
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
        self._refresh_options()

    def on_unmount(self) -> None:
        self._cancel_snapshot_worker()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if not self._loading and self._current_snapshot() is None:
            self._request_load(force=False)

    def on_refresh(self) -> None:
        self._request_load(force=True)

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
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> AgentsSnapshot | None:
        return self._snapshot

    def _request_load(self, *, force: bool) -> None:
        self._request_snapshot(force=force)

    def _on_snapshot_started(self, request: SnapshotRequest) -> None:
        del request
        self._update_status()

    def _build_snapshot(self, request: SnapshotRequest) -> _AgentsSnapshotResult:
        return _AgentsSnapshotResult(snapshot=load_agents_snapshot(request.project))

    def _accept_snapshot(self, result: Any, request: SnapshotRequest) -> bool:
        return (
            isinstance(result, _AgentsSnapshotResult)
            and result.snapshot.project == request.project
        )

    def _apply_snapshot(self, result: Any, request: SnapshotRequest) -> None:
        del request
        preferred = self.selected_entry_target()
        self._snapshot = result.snapshot
        self._load_error = None
        self._refresh_options(preferred_target=preferred)

    def _on_snapshot_error(self, error: str, request: SnapshotRequest) -> None:
        del request
        self._load_error = error
        self._update_status()

    @on(OptionList.OptionHighlighted, "#agents-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        self._update_static("#agents-hints", self._hints_text())

    @on(OptionList.OptionSelected, "#agents-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()


__all__ = ["ArtifactsAgentsPane"]
