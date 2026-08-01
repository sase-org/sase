"""Composition and off-thread lifecycle for the Artifacts Beads pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer

from .bead_filter_bar import BeadFilterBar
from .beads_data import BeadsSnapshot, load_beads_snapshot
from .beads_filter_session import BeadsFilterSessionMixin
from .beads_list import BeadRow
from .beads_navigation import BeadsNavigationMixin, BeadsOptionList
from .beads_options import BeadsOptionsMixin
from .lifecycle import ArtifactsPaneLifecycle

if TYPE_CHECKING:
    from ...app import AceApp


class ArtifactsBeadsPane(
    BeadsFilterSessionMixin,
    BeadsNavigationMixin,
    BeadsOptionsMixin,
    ArtifactsPaneLifecycle,
    Vertical,
):
    """Browse task beads and expandable epic phase trees."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._snapshot: BeadsSnapshot | None = None
        self._loading = False
        self._reload_pending = False
        self._force_pending = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._init_beads_navigation()
        self._init_beads_filter_session()
        self._init_beads_options()

    def compose(self) -> ComposeResult:
        yield BeadFilterBar(id="bead-filter-bar")
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="beads-info")
        with Horizontal(id="beads-panels"):
            list_panel = Vertical(id="beads-list-panel")
            list_panel.border_title = "Beads"
            with list_panel:
                yield Static(self._status_text(), id="beads-status")
                yield BeadsOptionList(id="beads-list")
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
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if self._snapshot is None or self._snapshot.project != self.project_scope:
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
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> BeadsSnapshot | None:
        return self._snapshot

    def _request_load(self, *, force: bool) -> None:
        project = self.project_scope
        if self._loading:
            self._reload_pending = True
            self._force_pending = self._force_pending or force
            return
        self._loading = True
        self._load_error = None
        self._update_static("#beads-status", self._status_text())
        previous = (
            self._snapshot
            if self._snapshot is not None and self._snapshot.project == project
            else None
        )

        def task() -> BeadsSnapshot:
            return load_beads_snapshot(project, previous=previous, force=force)

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            if (
                isinstance(result, BeadsSnapshot)
                and result.project == self.project_scope
            ):
                preferred = self._selected_option_id()
                cancel_jump = getattr(
                    self.app, "_cancel_artifacts_jump_mode_for_model_change", None
                )
                if callable(cancel_jump):
                    cancel_jump("beads")
                self._snapshot = result
                self._load_error = None
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options(preferred_id=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = str(event.worker.error or "Beads load failed")
            self._update_static("#beads-status", self._status_text())
            self._update_detail()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if terminal and self._reload_pending:
            force = self._force_pending
            self._reload_pending = False
            self._force_pending = False
            self.call_later(lambda: self._request_load(force=force))

    @on(OptionList.OptionHighlighted, "#beads-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    @on(OptionList.OptionSelected, "#beads-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast("AceApp", self.app).action_beads_view_selected()


__all__ = ["ArtifactsBeadsPane", "BeadRow"]
