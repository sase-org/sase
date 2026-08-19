"""The Memory panel -- browse one scope's SASE memory notes.

This module is the modal shell: the widget tree, the worker-backed loads
that fill it, and the passive source-file/copy actions. The panel's
behavior is split across sibling mixins -- snapshot and selection state in
:mod:`sase.ace.tui.modals.memory_panel_state`, widget rendering in
:mod:`sase.ace.tui.modals.memory_panel_view`, and note/filter/scope movement
in :mod:`sase.ace.tui.modals.memory_panel_navigation`. Link-chip travel and
add/edit/delete/publish surfaces are later phases and are not wired here;
the keymap scope already carries their bindings (see
``ace.keymaps.memory``), but no ``action_*`` method exists for them yet, so
those keys are safe, silent no-ops until a later phase implements them.
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
from sase.ace.tui.keymaps import (
    MemoryPanelKeymaps,
    build_memory_bindings,
    load_keymap_registry,
)
from sase.ace.tui.memory_panel_catalog import (
    MemoryRailNode,
    MemoryScopeRef,
    MemoryScopeSnapshot,
    load_memory_scope_snapshot,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.memory.notes import MemoryNote

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .memory_panel_help_modal import MemoryPanelHelpModal
from .memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryScopeChoice,
    load_memory_panel_initial_state,
    load_memory_scope_choices,
    note_digest_changed,
)
from .memory_panel_navigation import MemoryPanelNavigationMixin
from .memory_panel_rendering import memory_card_accent, memory_note_source_path
from .memory_panel_scope_picker import MemoryScopePicker
from .memory_panel_state import (
    _FILTER_INPUT_ID,
    _NOTE_LIST_ID,
    MemoryPanelStateMixin,
)
from .memory_panel_view import MemoryPanelViewMixin


class _MemoryFilterInput(FilterInput):
    """The panel's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def action_close_filter(self) -> None:
        panel = self._panel()
        if panel is not None:
            panel._close_filter()

    def _panel(self) -> MemoryPanel | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, MemoryPanel):
                return node
            node = getattr(node, "parent", None)
        return None


class MemoryPanel(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    MemoryPanelStateMixin,
    MemoryPanelViewMixin,
    MemoryPanelNavigationMixin,
    ModalScreen[None],
):
    """Browse one scope's memory notes, tree-ordered, with a filter."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        *,
        keymaps: MemoryPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        initial_note: str | None = None,
    ) -> None:
        super().__init__()
        self._keymaps = keymaps or load_keymap_registry({}).memory
        self._bindings = BindingsMap(
            [*build_memory_bindings(self._keymaps), *self.BINDINGS]
        )
        self._launch_workspace = launch_workspace
        self._initial_scope_key = initial_scope_key
        self._initial_note = initial_note
        self._accent = "#87D7FF"
        self._ring: tuple[MemoryScopeRef, ...] = ()
        self._scope_index = 0
        self._snapshot: MemoryScopeSnapshot | None = None
        self._all_rows: tuple[MemoryRailNode, ...] = ()
        self._rows: tuple[MemoryRailNode, ...] = ()
        self._current_note: str | None = None
        self._filter_text = ""
        self._filter_bodies = False
        self._loading = True
        self._load_worker: Worker[MemoryPanelInitialLoad] | None = None
        self._scope_worker: Worker[MemoryScopeSnapshot] | None = None
        self._picker_worker: Worker[tuple[MemoryScopeChoice, ...]] | None = None
        self._restat_worker: Worker[bool] | None = None
        self._selection_guard = ProgrammaticSelectionGuard()
        self._debouncer: DetailPanelDebouncer | None = None
        self._scope_selection_memory: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        self._accent = memory_card_accent(self.app.current_theme)
        with Container(id="memory-panel-container"):
            yield Static(self._loading_header_text(), id="memory-panel-header")
            with Horizontal(id="memory-panel-body"):
                yield OptionList(id=_NOTE_LIST_ID)
                with VerticalScroll(id="memory-panel-detail"):
                    yield Static("", id="memory-panel-card-title")
                    yield Static("", id="memory-panel-card-description")
                    yield Markdown("", id="memory-panel-card-body")
                    yield Static("", id="memory-panel-card-meta")
            yield _MemoryFilterInput(
                placeholder="Filter notes…",
                id=_FILTER_INPUT_ID,
            )
            yield Static("", id="memory-panel-trail")
            yield Static("", id="memory-panel-footer")

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app)
        self._filter_input().display = False
        self._trail_strip().display = False
        self._note_list().focus()
        self._start_initial_load()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
        for worker in (
            self._load_worker,
            self._scope_worker,
            self._picker_worker,
            self._restat_worker,
        ):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_resize(self, _event: events.Resize) -> None:
        """Re-fit the note rail when the terminal changes size."""
        self._resize_note_rail()

    # --- loading --------------------------------------------------------

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_note_card()
        self._update_footer()
        settings = getattr(self.app, "_current_project_settings", None)
        seed_from_current_project = getattr(settings, "seed_filters", True)

        def task() -> MemoryPanelInitialLoad:
            return load_memory_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_scope_key=self._initial_scope_key,
                seed_from_current_project=seed_from_current_project,
            )

        self._load_worker = self.run_worker(
            task, thread=True, exclusive=True, group="memory-panel-load"
        )

    def _start_scope_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_note_card()
        self._update_footer()
        ref = self._ring[self._scope_index]

        def task() -> MemoryScopeSnapshot:
            return load_memory_scope_snapshot(ref)

        self._scope_worker = self.run_worker(
            task, thread=True, exclusive=True, group="memory-panel-scope"
        )

    def _start_scope_picker_load(self) -> None:
        if self._picker_worker is not None and not self._picker_worker.is_finished:
            return
        ring = self._ring

        def task() -> tuple[MemoryScopeChoice, ...]:
            return load_memory_scope_choices(ring)

        self._picker_worker = self.run_worker(
            task, thread=True, exclusive=True, group="memory-panel-scope-picker"
        )

    def _start_restat(self, note: MemoryNote) -> None:
        if self._restat_worker is not None and not self._restat_worker.is_finished:
            self._restat_worker.cancel()
        if not self._ring:
            return
        scope = self._ring[self._scope_index]
        previous = (
            self._snapshot.digests.get(note.relative_path) if self._snapshot else None
        )

        def task() -> bool:
            return note_digest_changed(scope, note, previous)

        self._restat_worker = self.run_worker(
            task, thread=True, exclusive=True, group="memory-panel-restat"
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_initial_load_state_changed(event)
        elif event.worker is self._scope_worker:
            self._on_scope_load_state_changed(event)
        elif event.worker is self._picker_worker:
            self._on_scope_picker_load_state_changed(event)
        elif event.worker is self._restat_worker:
            self._on_restat_state_changed(event)

    def _on_initial_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, MemoryPanelInitialLoad):
                return
            self._loading = False
            self._ring = result.ring
            self._scope_index = result.scope_index
            self._apply_snapshot(result.snapshot, preferred_note=self._initial_note)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
            self._apply_snapshot(None, preferred_note=None)

    def _on_scope_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, MemoryScopeSnapshot):
                return
            if not self._ring or result.scope.key != self._ring[self._scope_index].key:
                return  # Stale: the user cycled again before this load landed.
            self._loading = False
            preferred = self._scope_selection_memory.get(result.scope.key)
            self._apply_snapshot(result, preferred_note=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._update_header()
            self._render_note_card()
            self._update_footer()

    def _on_scope_picker_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple):
            return
        if not self.is_mounted or not self._ring:
            return
        current_key = self._ring[self._scope_index].key
        self.app.push_screen(
            MemoryScopePicker(result, current_key=current_key), self._on_scope_picked
        )

    def _on_scope_picked(self, key: str | None) -> None:
        if key is None or not self._ring or self._loading:
            return
        for index, ref in enumerate(self._ring):
            if ref.key != key:
                continue
            if index == self._scope_index:
                return
            if self._snapshot is not None:
                self._scope_selection_memory[self._snapshot.scope.key] = (
                    self._current_note or ""
                )
            self._scope_index = index
            self._filter_input().value = ""
            self._filter_input().display = False
            self._start_scope_load()
            return

    def _on_restat_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return
        changed = event.worker.result
        if not changed or self._loading or not self._ring:
            return
        self._start_scope_load()

    # --- passive actions ------------------------------------------------

    def _source_action_path(self) -> str | None:
        node = self._selected_row()
        if node is None or not self._ring:
            return None
        return memory_note_source_path(self._ring[self._scope_index], node.note)

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return None, None

    def action_open_source(self) -> None:
        node = self._selected_row()
        self.action_open_in_editor()
        if node is not None:
            self._start_restat(node.note)

    def action_open_viewer(self) -> None:
        self.action_open_in_viewer()

    def action_copy_source_path(self) -> None:
        self.action_copy_path()

    def action_copy_body(self) -> None:
        node = self._selected_row()
        if node is None:
            return
        schedule_copy_delivery(
            self,
            node.note.body.strip(),
            copied_label="memory note body",
            task_name="sase-memory-panel-copy-body",
        )

    def action_help(self) -> None:
        self.app.push_screen(MemoryPanelHelpModal(keymaps=self._keymaps))

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["MemoryPanel"]
