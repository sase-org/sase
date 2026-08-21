"""The Snippets panel -- browse and edit one project's snippet catalog.

This module is the modal shell: the widget tree, the worker-backed loads that
fill it, and the passive source-file/copy actions. The panel's behavior is
split across sibling mixins -- snapshot and selection state in
:mod:`sase.ace.tui.modals.snippets_panel_state`, widget rendering in
:mod:`sase.ace.tui.modals.snippets_panel_view`, trigger/filter/project
movement in :mod:`sase.ace.tui.modals.snippets_panel_navigation`,
relation-chip travel in :mod:`sase.ace.tui.modals.snippets_panel_travel`,
and add/edit/delete in :mod:`sase.ace.tui.modals.snippets_panel_actions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.keymaps import (
    SnippetPanelKeymaps,
    build_snippet_bindings,
    load_keymap_registry,
)
from sase.ace.tui.snippets_panel_catalog import (
    SnippetProjectRef,
    SnippetProjectSnapshot,
    load_snippet_project_snapshot,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.snippet.models import SnippetEntry

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .snippets_panel_actions import SnippetsPanelActionsMixin
from .snippets_panel_add import SnippetFormDraft
from .snippets_panel_help_modal import SnippetsPanelHelpModal
from .snippets_panel_load import (
    SnippetsPanelInitialLoad,
    load_snippets_panel_initial_state,
)
from .snippets_panel_navigation import SnippetsPanelNavigationMixin
from .snippets_panel_rendering import snippet_card_accent
from .snippets_panel_state import (
    _FILTER_INPUT_ID,
    _TRIGGER_LIST_ID,
    SnippetsPanelStateMixin,
)
from .snippets_panel_travel import SnippetsPanelTravelMixin
from .snippets_panel_view import SnippetsPanelViewMixin

_SESSION_TRIGGER_LIMIT = 64


@dataclass
class SnippetsPaneSessionState:
    """Session-only cursor state for an embedded Snippets content pane."""

    active_project_key: str | None = None
    selected_trigger: str | None = None
    project_triggers: dict[str, str] = field(default_factory=dict)

    def trigger_for_project(self, project_key: str) -> str | None:
        return self.project_triggers.get(project_key) or self.selected_trigger

    def record_project(self, project_key: str | None) -> None:
        self.active_project_key = project_key

    def record_selection(self, project_key: str | None, trigger: str | None) -> None:
        self.selected_trigger = trigger
        if project_key is None:
            return
        if trigger:
            self.project_triggers[project_key] = trigger
            self._trim_project_triggers(project_key)
        else:
            self.project_triggers.pop(project_key, None)

    def _trim_project_triggers(self, keep_key: str) -> None:
        while len(self.project_triggers) > _SESSION_TRIGGER_LIMIT:
            oldest = next(iter(self.project_triggers))
            if oldest == keep_key and len(self.project_triggers) > 1:
                oldest = next(key for key in self.project_triggers if key != keep_key)
            self.project_triggers.pop(oldest, None)


class SnippetsPaneHost(Protocol):
    """Host callback required by :class:`SnippetsPane` for close requests."""

    def close_snippets_pane(self) -> None: ...


class _SnippetsFilterInput(FilterInput):
    """The panel's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)

    def action_close_filter(self) -> None:
        panel = self._panel()
        if panel is not None:
            panel._close_filter()

    def _panel(self) -> SnippetsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, SnippetsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class SnippetsPane(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    SnippetsPanelActionsMixin,
    SnippetsPanelStateMixin,
    SnippetsPanelViewMixin,
    SnippetsPanelNavigationMixin,
    SnippetsPanelTravelMixin,
    Vertical,
):
    """Reusable Snippets content pane, alphabetically browsed with a filter."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        *(
            (
                str(number),
                f"follow_relation_number({number})",
                f"Follow relation {number}",
            )
            for number in range(1, 10)
        ),
    ]

    def __init__(
        self,
        *,
        keymaps: SnippetPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        initial_trigger: str | None = None,
        session_state: SnippetsPaneSessionState | None = None,
        host: SnippetsPaneHost | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._host = host
        self._session_state = session_state or SnippetsPaneSessionState()
        self._host_visible = True
        self._keymaps = keymaps or load_keymap_registry({}).snippets
        self._bindings = BindingsMap(
            [*build_snippet_bindings(self._keymaps), *self.BINDINGS]
        )
        self._launch_workspace = launch_workspace
        self._initial_project_key = initial_project_key
        self._initial_trigger = initial_trigger
        self._accent = "#87D7FF"
        self._ring: tuple[SnippetProjectRef, ...] = ()
        self._project_index = 0
        self._snapshot: SnippetProjectSnapshot | None = None
        self._all_entries: tuple[SnippetEntry, ...] = ()
        self._entries: tuple[SnippetEntry, ...] = ()
        self._current_trigger: str | None = None
        self._filter_text = ""
        self._filter_bodies = False
        self._loading = True
        self._load_worker: Worker[SnippetsPanelInitialLoad] | None = None
        self._project_worker: Worker[SnippetProjectSnapshot] | None = None
        self._selection_guard = ProgrammaticSelectionGuard()
        self._debouncer: DetailPanelDebouncer | None = None
        self._project_selection_memory = self._session_state.project_triggers
        self._chip_entries: tuple[SnippetEntry, ...] = ()
        self._chip_outbound_count = 0
        self._chip_cursor: int | None = None
        self._trail: list[str] = []
        self._write_busy = False
        self._pending_delete_trigger: str | None = None
        self._pending_delete_neighbor: str | None = None
        self._pending_draft: SnippetFormDraft | None = None

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_subtab_select_key

        if handle_config_hub_subtab_select_key(self, event):
            return
        super().on_key(event)

    def compose(self) -> ComposeResult:
        self._accent = snippet_card_accent(self.app.current_theme)
        with Container(id="snippets-panel-container"):
            yield Static(self._loading_header_text(), id="snippets-panel-header")
            with Horizontal(id="snippets-panel-body"):
                yield OptionList(id=_TRIGGER_LIST_ID)
                with VerticalScroll(id="snippets-panel-detail"):
                    yield Static("", id="snippets-panel-card-title")
                    yield Static("", id="snippets-panel-card-raw")
                    yield Static("", id="snippets-panel-card-composed")
                    yield Static("", id="snippets-panel-card-meta")
            yield _SnippetsFilterInput(
                placeholder="Filter triggers and sources…",
                id=_FILTER_INPUT_ID,
            )
            yield Static("", id="snippets-panel-trail")
            yield Static("", id="snippets-panel-footer")

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app)
        self._filter_input().display = False
        self._trail_strip().display = False
        self._trigger_list().focus()
        self._start_initial_load()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
        for worker in (self._load_worker, self._project_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def focus_default(self) -> None:
        """Focus the trigger rail when the Snippets pane becomes active."""
        try:
            self._trigger_list().focus()
        except Exception:
            pass

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Receive visibility activation from an embedding Admin Center host."""
        self._host_visible = active
        if active:
            self.focus_default()

    def on_resize(self, _event: events.Resize) -> None:
        """Re-fit the trigger rail when the terminal changes size."""
        self._resize_trigger_rail()

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_snippet_card()
        self._update_footer()
        settings = getattr(self.app, "_current_project_settings", None)
        seed_from_current_project = getattr(settings, "seed_filters", True)
        session_project = (
            None
            if self._initial_project_key is not None or self._initial_trigger
            else self._session_state.active_project_key
        )
        initial_project_key = self._initial_project_key or session_project

        def task() -> SnippetsPanelInitialLoad:
            return load_snippets_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_project_key=initial_project_key,
                seed_from_current_project=seed_from_current_project,
            )

        self._load_worker = self.run_worker(
            task, thread=True, exclusive=True, group="snippets-panel-load"
        )

    def _start_project_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_snippet_card()
        self._update_footer()
        ref = self._ring[self._project_index]

        def task() -> SnippetProjectSnapshot:
            return load_snippet_project_snapshot(ref)

        self._project_worker = self.run_worker(
            task, thread=True, exclusive=True, group="snippets-panel-project"
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_initial_load_state_changed(event)
        elif event.worker is self._project_worker:
            self._on_project_load_state_changed(event)

    def _on_initial_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, SnippetsPanelInitialLoad):
                return
            self._loading = False
            self._ring = result.ring
            self._project_index = result.project_index
            project_key = self._active_project_key_from_ring()
            self._record_session_project(project_key)
            preferred = self._initial_trigger
            if preferred is None and project_key is not None:
                preferred = self._session_state.trigger_for_project(project_key)
            self._apply_snapshot(result.snapshot, preferred_trigger=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
            self._record_session_project(None)
            self._apply_snapshot(None, preferred_trigger=None)

    def _on_project_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, SnippetProjectSnapshot):
                return
            if (
                not self._ring
                or result.project.key != self._ring[self._project_index].key
            ):
                return  # Stale: the user cycled again before this load landed.
            self._loading = False
            self._record_session_project(result.project.key)
            preferred = self._session_state.trigger_for_project(result.project.key)
            self._apply_snapshot(result, preferred_trigger=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._update_header()
            self._render_snippet_card()
            self._update_footer()

    def _active_project_key_from_ring(self) -> str | None:
        if not self._ring or not 0 <= self._project_index < len(self._ring):
            return None
        return self._ring[self._project_index].key

    def _record_session_project(self, project_key: str | None) -> None:
        self._session_state.record_project(project_key)

    def _record_session_selection(self) -> None:
        project_key = (
            self._snapshot.project.key
            if self._snapshot is not None
            else self._active_project_key_from_ring()
        )
        self._session_state.record_selection(project_key, self._current_trigger)

    def _source_action_path(self) -> str | None:
        entry = self._selected_entry()
        if entry is None:
            return None
        return entry.origin.path or entry.origin.display_path

    def action_open_source(self) -> None:
        self.action_open_in_editor()

    def action_open_viewer(self) -> None:
        self.action_open_in_viewer()

    def action_copy_source_path(self) -> None:
        self.action_copy_path()

    def action_copy_template(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        schedule_copy_delivery(
            self,
            entry.raw_template,
            copied_label="snippet template",
            task_name="sase-snippets-panel-copy-template",
        )

    def action_help(self) -> None:
        self.app.push_screen(SnippetsPanelHelpModal(keymaps=self._keymaps))

    def action_close(self) -> None:
        if self._host is not None:
            self._host.close_snippets_pane()


class SnippetsPanel(CopyModeForwardingMixin, ModalScreen[None]):
    """Standalone modal adapter for :class:`SnippetsPane`."""

    def __init__(
        self,
        *,
        keymaps: SnippetPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        initial_trigger: str | None = None,
        session_state: SnippetsPaneSessionState | None = None,
    ) -> None:
        super().__init__()
        self._pane = SnippetsPane(
            keymaps=keymaps,
            launch_workspace=launch_workspace,
            initial_project_key=initial_project_key,
            initial_trigger=initial_trigger,
            session_state=session_state,
            host=self,
            id="snippets-panel-pane",
        )

    @property
    def pane(self) -> SnippetsPane:
        return self._pane

    def compose(self) -> ComposeResult:
        yield self._pane

    def focus_default(self) -> None:
        self._pane.focus_default()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self._pane.on_center_tab_visibility_changed(active)

    def close_snippets_pane(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.close_snippets_pane()

    def __getattr__(self, name: str) -> Any:
        pane = self.__dict__.get("_pane")
        if pane is not None:
            try:
                return getattr(pane, name)
            except AttributeError:
                pass
        raise AttributeError(
            f"{type(self).__name__!s} object has no attribute {name!r}"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_trail" and "_pane" in self.__dict__:
            setattr(self.__dict__["_pane"], name, value)
            return
        super().__setattr__(name, value)


__all__ = [
    "SnippetsPane",
    "SnippetsPaneHost",
    "SnippetsPaneSessionState",
    "SnippetsPanel",
]
