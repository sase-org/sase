"""Composition and lifecycle for the Artifacts plans pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.debounce import DetailPanelDebouncer

from .panes import ArtifactsPaneLifecycle
from .plan_filter_bar import PlanFilterBar
from .plans_data import PlansSnapshot, load_plans_snapshot
from .plans_deep_archive import DEEP_ARCHIVE_DEBOUNCE_S
from .plans_filter_session import PlansFilterSessionMixin
from .plans_list import PlanRow, build_plan_options
from .plans_navigation import PlansNavigationMixin
from .plans_options import PlansOptionsMixin
from .plans_rendering import (
    archive_text,
    epic_text,
    phase_text,
    project_badge,
    proposal_text,
)

if TYPE_CHECKING:
    from ...app import AceApp


# Preserve the rendering seams exposed by the original plans_pane module.
_proposal_text = proposal_text
_epic_text = epic_text
_phase_text = phase_text
_archive_text = archive_text
_project_badge = project_badge


class ArtifactsPlansPane(
    PlansFilterSessionMixin,
    PlansNavigationMixin,
    PlansOptionsMixin,
    ArtifactsPaneLifecycle,
    Vertical,
):
    """Browse proposals, epic phase trees, and committed plan markdown."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._snapshot: PlansSnapshot | None = None
        self._loading = False
        self._reload_pending = False
        self._force_pending = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._init_plans_navigation()
        self._init_plans_filter_session()
        self._init_plans_options()

    def compose(self) -> ComposeResult:
        yield PlanFilterBar(id="plan-filter-bar")
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="plans-info")
        with Horizontal(id="plans-panels"):
            list_panel = Vertical(id="plans-list-panel")
            list_panel.border_title = "Plan pipeline"
            with list_panel:
                yield Static(self._status_text(), id="plans-status")
                yield OptionList(id="plans-list")
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
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()
        if (
            self._deep_archive_worker is not None
            and not self._deep_archive_worker.is_finished
        ):
            self._deep_archive_worker.cancel()

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
        self._load_error = None
        self._reset_deep_archive_state()
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> PlansSnapshot | None:
        return self._snapshot

    def _request_load(self, *, force: bool) -> None:
        project = self.project_scope
        if self._loading:
            self._reload_pending = True
            self._force_pending = self._force_pending or force
            return
        self._loading = True
        self._load_error = None
        self._update_status()
        previous = (
            self._snapshot
            if self._snapshot is not None and self._snapshot.project == project
            else None
        )

        def task() -> PlansSnapshot:
            return load_plans_snapshot(project, previous=previous, force=force)

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._deep_archive_worker:
            self._on_deep_archive_worker_changed(event)
            return
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
                isinstance(result, PlansSnapshot)
                and result.project == self.project_scope
            ):
                preferred = self._selected_option_id()
                cancel_jump = getattr(
                    self.app, "_cancel_artifacts_jump_mode_for_model_change", None
                )
                if callable(cancel_jump):
                    cancel_jump("plans")
                snapshot_changed = result is not self._snapshot
                self._snapshot = result
                self._filter_index = None
                self._filter_index_snapshot = None
                if snapshot_changed:
                    self._reset_deep_archive_state()
                self._load_error = None
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options(preferred_id=preferred)
                self._schedule_deep_archive(self._display_filter_values())
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = str(event.worker.error or "Plans load failed")
            self._update_status()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if terminal and self._reload_pending:
            force = self._force_pending
            self._reload_pending = False
            self._force_pending = False
            self.call_later(lambda: self._request_load(force=force))

    @on(OptionList.OptionHighlighted, "#plans-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    @on(OptionList.OptionSelected, "#plans-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast("AceApp", self.app).action_plans_view_selected()


__all__ = ["ArtifactsPlansPane", "PlanRow"]
