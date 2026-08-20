"""The Snippets panel -- browse one project's snippet catalog.

This module is the modal shell: the widget tree, the worker-backed loads that
fill it, and the passive source-file/copy actions. The panel's behavior is
split across sibling mixins -- snapshot and selection state in
:mod:`sase.ace.tui.modals.snippets_panel_state`, widget rendering in
:mod:`sase.ace.tui.modals.snippets_panel_view`, trigger/filter/project
movement in :mod:`sase.ace.tui.modals.snippets_panel_navigation`, and
relation-chip travel in :mod:`sase.ace.tui.modals.snippets_panel_travel`.

The panel is intentionally unregistered from prompt keymaps in this phase so
partial browsing work is not user-reaching.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, VerticalScroll
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


class _SnippetsFilterInput(FilterInput):
    """The panel's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def action_close_filter(self) -> None:
        panel = self._panel()
        if panel is not None:
            panel._close_filter()

    def _panel(self) -> SnippetsPanel | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, SnippetsPanel):
                return node
            node = getattr(node, "parent", None)
        return None


class SnippetsPanel(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    SnippetsPanelStateMixin,
    SnippetsPanelViewMixin,
    SnippetsPanelNavigationMixin,
    SnippetsPanelTravelMixin,
    ModalScreen[None],
):
    """Browse one project's snippets, alphabetically, with a filter."""

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
    ) -> None:
        super().__init__()
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
        self._project_selection_memory: dict[str, str] = {}
        self._chip_entries: tuple[SnippetEntry, ...] = ()
        self._chip_outbound_count = 0
        self._chip_cursor: int | None = None
        self._trail: list[str] = []

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

        def task() -> SnippetsPanelInitialLoad:
            return load_snippets_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_project_key=self._initial_project_key,
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
            self._apply_snapshot(
                result.snapshot, preferred_trigger=self._initial_trigger
            )
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
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
            preferred = self._project_selection_memory.get(result.project.key)
            self._apply_snapshot(result, preferred_trigger=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._update_header()
            self._render_snippet_card()
            self._update_footer()

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
        self.dismiss(None)


__all__ = ["SnippetsPanel"]
