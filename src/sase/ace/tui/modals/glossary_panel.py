"""The Glossary panel -- browse one project's glossary terms.

This module is the modal shell: the widget tree, the worker-backed loads that
fill it, and the passive source-file/copy actions. The panel's behavior is
split across sibling mixins -- snapshot and selection state in
:mod:`sase.ace.tui.modals.glossary_panel_state`, widget rendering in
:mod:`sase.ace.tui.modals.glossary_panel_view`, term/filter/project movement in
:mod:`sase.ace.tui.modals.glossary_panel_navigation`, relation-chip travel in
:mod:`sase.ace.tui.modals.glossary_panel_travel`, and add/delete in
:mod:`sase.ace.tui.modals.glossary_panel_actions`.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
    load_glossary_project_snapshot,
)
from sase.ace.tui.keymaps import (
    GlossaryPanelKeymaps,
    build_glossary_bindings,
    load_keymap_registry,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.core.glossary_facade import GlossaryEntry

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .glossary_panel_actions import GlossaryPanelActionsMixin
from .glossary_panel_help_modal import GlossaryPanelHelpModal
from .glossary_panel_load import (
    GlossaryPanelInitialLoad,
    load_glossary_panel_initial_state,
)
from .glossary_panel_navigation import GlossaryPanelNavigationMixin
from .glossary_panel_state import (
    _FILTER_INPUT_ID,
    _TERM_LIST_ID,
    GlossaryPanelStateMixin,
)
from .glossary_panel_travel import GlossaryPanelTravelMixin
from .glossary_panel_view import GlossaryPanelViewMixin
from .glossary_preview_render import (
    glossary_card_accent,
    glossary_definition_position,
    glossary_source_path,
)


class _GlossaryFilterInput(FilterInput):
    """The panel's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def action_close_filter(self) -> None:
        panel = self._panel()
        if panel is not None:
            panel._close_filter()

    def _panel(self) -> GlossaryPanel | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, GlossaryPanel):
                return node
            node = getattr(node, "parent", None)
        return None


class GlossaryPanel(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    GlossaryPanelActionsMixin,
    GlossaryPanelStateMixin,
    GlossaryPanelViewMixin,
    GlossaryPanelNavigationMixin,
    GlossaryPanelTravelMixin,
    ModalScreen[None],
):
    """Browse one project's glossary terms, alphabetically, with a filter."""

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
        keymaps: GlossaryPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        initial_term: str | None = None,
    ) -> None:
        super().__init__()
        self._keymaps = keymaps or load_keymap_registry({}).glossary
        self._bindings = BindingsMap(
            [*build_glossary_bindings(self._keymaps), *self.BINDINGS]
        )
        self._launch_workspace = launch_workspace
        self._initial_project_key = initial_project_key
        self._initial_term = initial_term
        self._accent = "#87D7FF"
        self._ring: tuple[GlossaryProjectRef, ...] = ()
        self._project_index = 0
        self._snapshot: GlossaryProjectSnapshot | None = None
        self._all_entries: tuple[GlossaryEntry, ...] = ()
        self._entries: tuple[GlossaryEntry, ...] = ()
        self._current_term: str | None = None
        self._filter_text = ""
        self._filter_definitions = False
        self._loading = True
        self._load_worker: Worker[GlossaryPanelInitialLoad] | None = None
        self._project_worker: Worker[GlossaryProjectSnapshot] | None = None
        self._selection_guard = ProgrammaticSelectionGuard()
        self._debouncer: DetailPanelDebouncer | None = None
        self._project_selection_memory: dict[str, str] = {}
        self._chip_entries: tuple[GlossaryEntry, ...] = ()
        self._chip_outbound_count = 0
        self._chip_cursor: int | None = None
        self._trail: list[str] = []
        self._write_busy = False
        self._pending_delete_term: str | None = None
        self._pending_delete_neighbor: str | None = None

    def compose(self) -> ComposeResult:
        self._accent = glossary_card_accent(self.app.current_theme)
        with Container(id="glossary-panel-container"):
            yield Static(self._loading_header_text(), id="glossary-panel-header")
            with Horizontal(id="glossary-panel-body"):
                yield OptionList(id=_TERM_LIST_ID)
                with VerticalScroll(id="glossary-panel-detail"):
                    yield Static("", id="glossary-panel-card-title")
                    yield Markdown("", id="glossary-panel-card-definition")
                    yield Static("", id="glossary-panel-card-meta")
            yield _GlossaryFilterInput(
                placeholder="Filter terms and aliases…",
                id=_FILTER_INPUT_ID,
            )
            yield Static("", id="glossary-panel-trail")
            yield Static("", id="glossary-panel-footer")

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app)
        self._filter_input().display = False
        self._trail_strip().display = False
        self._term_list().focus()
        self._start_initial_load()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
        for worker in (self._load_worker, self._project_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_resize(self, _event: events.Resize) -> None:
        """Re-fit the term rail when the terminal changes size."""
        self._resize_term_rail()

    # --- loading --------------------------------------------------------

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_definition_card()
        self._update_footer()
        settings = getattr(self.app, "_current_project_settings", None)
        seed_from_current_project = getattr(settings, "seed_filters", True)

        def task() -> GlossaryPanelInitialLoad:
            return load_glossary_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_project_key=self._initial_project_key,
                seed_from_current_project=seed_from_current_project,
            )

        self._load_worker = self.run_worker(
            task, thread=True, exclusive=True, group="glossary-panel-load"
        )

    def _start_project_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_definition_card()
        self._update_footer()
        ref = self._ring[self._project_index]

        def task() -> GlossaryProjectSnapshot:
            return load_glossary_project_snapshot(ref)

        self._project_worker = self.run_worker(
            task, thread=True, exclusive=True, group="glossary-panel-project"
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_initial_load_state_changed(event)
        elif event.worker is self._project_worker:
            self._on_project_load_state_changed(event)

    def _on_initial_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, GlossaryPanelInitialLoad):
                return
            self._loading = False
            self._ring = result.ring
            self._project_index = result.project_index
            self._apply_snapshot(result.snapshot, preferred_term=self._initial_term)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
            self._apply_snapshot(None, preferred_term=None)

    def _on_project_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, GlossaryProjectSnapshot):
                return
            if (
                not self._ring
                or result.project.key != self._ring[self._project_index].key
            ):
                return  # Stale: the user cycled again before this load landed.
            self._loading = False
            preferred = self._project_selection_memory.get(result.project.key)
            self._apply_snapshot(result, preferred_term=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._update_header()
            self._render_definition_card()
            self._update_footer()

    # --- passive actions ------------------------------------------------

    def _source_action_path(self) -> str | None:
        entry = self._selected_entry()
        if entry is None or self._snapshot is None or self._snapshot.catalog is None:
            return None
        return glossary_source_path(self._snapshot.catalog, entry)

    def _source_action_position(self) -> tuple[int | None, int | None]:
        entry = self._selected_entry()
        if entry is None:
            return None, None
        return glossary_definition_position(entry)

    def action_open_source(self) -> None:
        self.action_open_in_editor()

    def action_open_viewer(self) -> None:
        self.action_open_in_viewer()

    def action_copy_source_path(self) -> None:
        self.action_copy_path()

    def action_copy_definition(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        schedule_copy_delivery(
            self,
            entry.definition.strip(),
            copied_label="glossary definition",
            task_name="sase-glossary-panel-copy-definition",
        )

    def action_help(self) -> None:
        self.app.push_screen(GlossaryPanelHelpModal(keymaps=self._keymaps))

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["GlossaryPanel"]
