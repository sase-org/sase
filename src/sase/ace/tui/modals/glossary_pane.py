"""Reusable Glossary content pane for the standalone modal and Config hub.

Composition, scoped bindings, worker-backed loads, debouncing, selection
guard, relationship travel, mutations, and source/copy/help actions live
here. :class:`GlossaryPanel` is a thin modal adapter that hosts this pane
and dismisses itself on close.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
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
from .catalog_pane_contract import CatalogPaneHost, CatalogPaneSession
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
    """The pane's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def action_close_filter(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane._close_filter()

    def _pane(self) -> GlossaryPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, GlossaryPane):
                return node
            node = getattr(node, "parent", None)
        return None


class GlossaryPane(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    GlossaryPanelActionsMixin,
    GlossaryPanelStateMixin,
    GlossaryPanelViewMixin,
    GlossaryPanelNavigationMixin,
    GlossaryPanelTravelMixin,
    Vertical,
):
    """Browse one project's glossary terms, alphabetically, with a filter."""

    can_focus = False
    DEFAULT_CSS = """
    GlossaryPane {
        width: 100%;
        height: 100%;
        layout: vertical;
    }
    """
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
        host: CatalogPaneHost | None = None,
        session: CatalogPaneSession | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._keymaps = keymaps or load_keymap_registry({}).glossary
        self._bindings = BindingsMap(
            [*build_glossary_bindings(self._keymaps), *self.BINDINGS]
        )
        self._host = host
        self._session = session
        self._host_visible = True
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
        self.query_one("#glossary-panel-detail", VerticalScroll).can_focus = False
        self.focus_default()
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

    def focus_default(self) -> None:
        """Focus the term list when this pane is the active surface."""
        if not self._host_visible:
            return
        try:
            target = (
                self._filter_input()
                if self._filter_input().display
                else self._term_list()
            )
            self.app.set_focus(target)
        except Exception:
            pass

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause focus and pending card paints while another tab is showing."""
        self._host_visible = active
        if active:
            self._render_definition_card()
            self._update_header()
            self._update_footer()
            return
        if self._debouncer is not None:
            self._debouncer.cancel()

    def action_close(self) -> None:
        if self._host is not None:
            self._host.request_close()

    # --- loading --------------------------------------------------------

    def _preferred_initial_term(self) -> str | None:
        if self._initial_term is not None:
            return self._initial_term
        if self._session is not None:
            return self._session.entry_id
        return None

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_definition_card()
        self._update_footer()
        settings = getattr(self.app, "_current_project_settings", None)
        seed_from_current_project = getattr(settings, "seed_filters", True)
        session_project_key = (
            None
            if self._initial_project_key is not None or self._session is None
            else self._session.scope_key
        )

        def task() -> GlossaryPanelInitialLoad:
            return load_glossary_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_project_key=self._initial_project_key,
                seed_from_current_project=seed_from_current_project,
                session_project_key=session_project_key,
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
            self._apply_snapshot(
                result.snapshot, preferred_term=self._preferred_initial_term()
            )
            self.focus_default()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
            self._apply_snapshot(None, preferred_term=None)
            self.focus_default()

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


__all__ = ["GlossaryPane"]
