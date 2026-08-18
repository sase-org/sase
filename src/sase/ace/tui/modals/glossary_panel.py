"""The Glossary panel -- browse one project's glossary terms.

Beyond the modal shell (header, alphabetical term list, filter, `p`/`P`
project cycling), this module renders the definition card's numbered SEE
ALSO / REFERENCED BY relation chips and implements the second navigation
axis: the chip cursor, digit shortcuts, follow/back travel, and the bounded
breadcrumb trail. Add/delete live in
:mod:`sase.ace.tui.modals.glossary_panel_actions`.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
    glossary_entry_relations,
    invalidate_glossary_project,
    load_glossary_project_snapshot,
)
from sase.ace.tui.keymaps import (
    GlossaryPanelKeymaps,
    build_glossary_bindings,
    load_keymap_registry,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.core.glossary_facade import GlossaryEntry
from sase.glossary.text_filter import filter_glossary_entries

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .glossary_panel_actions import GlossaryPanelActionsMixin
from .glossary_panel_help_modal import GlossaryPanelHelpModal
from .glossary_panel_load import (
    GlossaryPanelInitialLoad,
    load_glossary_panel_initial_state,
)
from .glossary_panel_rendering import (
    build_definition_card_meta,
    build_definition_card_title,
    build_diagnostics_message,
    build_empty_project_message,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_term_row_text,
    build_trail_strip,
    sorted_glossary_entries,
)
from .glossary_preview_render import (
    glossary_card_accent,
    glossary_definition_markdown,
    glossary_definition_position,
    glossary_source_path,
)

_TERM_LIST_ID = "glossary-panel-terms"
_FILTER_INPUT_ID = "glossary-panel-filter"
_MAX_TRAIL_LENGTH = 32


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

    # --- loading --------------------------------------------------------

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_definition_card()
        self._update_footer()

        def task() -> GlossaryPanelInitialLoad:
            return load_glossary_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_project_key=self._initial_project_key,
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

    # --- state application ----------------------------------------------

    def _apply_snapshot(
        self, snapshot: GlossaryProjectSnapshot | None, *, preferred_term: str | None
    ) -> None:
        self._snapshot = snapshot
        self._all_entries = sorted_glossary_entries(
            snapshot.catalog if snapshot is not None else None
        )
        self._apply_filter(
            self._filter_text,
            definitions=self._filter_definitions,
            preferred_term=preferred_term,
        )

    def _apply_filter(
        self,
        pattern: str,
        *,
        definitions: bool,
        preferred_term: str | None = None,
    ) -> None:
        self._filter_text = pattern
        self._filter_definitions = definitions
        entries = filter_glossary_entries(
            self._all_entries,
            pattern=pattern or None,
            include_definitions=definitions,
        )
        preferred = preferred_term if preferred_term is not None else self._current_term
        self._set_entries(entries, preferred_term=preferred)
        self._update_header()
        self._update_footer()

    def _set_entries(
        self, entries: tuple[GlossaryEntry, ...], *, preferred_term: str | None
    ) -> None:
        option_list = self._term_list()
        prior_row = self._current_term_row()
        row = restore_selection_by_identity(
            entries,
            prior_identity=preferred_term,
            prior_visual_row=prior_row,
            identity_fn=lambda entry: entry.term,
        )
        self._entries = entries
        self._selection_guard.clear()
        option_list.clear_options()
        option_list.add_options(
            Option(build_term_row_text(entry), id=str(entry.index)) for entry in entries
        )
        if entries:
            identity = entries[row].term
            self._selection_guard.prepare(identity, row)
            option_list.highlighted = row
            self._current_term = identity
        else:
            self._current_term = None
        self._refresh_relations_for_current_entry()
        self._render_definition_card()

    # --- rendering --------------------------------------------------------

    def _loading_header_text(self) -> Text:
        return Text("GLOSSARY  ·  loading…", style=f"bold {self._accent}")

    def _update_header(self) -> None:
        header: RenderableType
        if self._loading:
            header = self._loading_header_text()
        else:
            project_display_name = (
                self._snapshot.project.display_name if self._snapshot else ""
            )
            header = build_panel_header(
                project_display_name=project_display_name,
                term_count=len(self._all_entries),
                project_index=self._project_index,
                project_count=len(self._ring),
                accent=self._accent,
            )
        self.query_one("#glossary-panel-header", Static).update(header)

    def _update_footer(self) -> None:
        entry = self._selected_entry()
        has_source_path = (
            entry is not None
            and self._snapshot is not None
            and self._snapshot.catalog is not None
            and glossary_source_path(self._snapshot.catalog, entry) is not None
        )
        focused_relation_term = None
        if self._chip_cursor is not None and 0 <= self._chip_cursor < len(
            self._chip_entries
        ):
            focused_relation_term = self._chip_entries[self._chip_cursor].term
        footer = build_panel_footer(
            self._keymaps,
            has_entries=bool(self._entries),
            has_source_path=has_source_path,
            ring_size=len(self._ring),
            has_relations=bool(self._chip_entries),
            has_trail=bool(self._trail),
            focused_relation_term=focused_relation_term,
        )
        footer_widget = self.query_one("#glossary-panel-footer", Static)
        footer_widget.update(footer)
        footer_widget.display = bool(footer)

    def _trail_strip(self) -> Static:
        return self.query_one("#glossary-panel-trail", Static)

    def _update_trail_strip(self) -> None:
        trail_widget = self._trail_strip()
        if not self._trail or self._current_term is None:
            trail_widget.display = False
            trail_widget.update("")
            return
        trail_widget.display = True
        trail_widget.update(
            build_trail_strip((*self._trail, self._current_term), accent=self._accent)
        )

    def _render_definition_card(self) -> None:
        self._update_trail_strip()
        title_widget = self.query_one("#glossary-panel-card-title", Static)
        definition_widget = self.query_one("#glossary-panel-card-definition", Markdown)
        meta_widget = self.query_one("#glossary-panel-card-meta", Static)

        if self._loading:
            title_widget.update("")
            definition_widget.update("Loading…")
            meta_widget.update("")
            return

        snapshot = self._snapshot
        if snapshot is None or not self._ring:
            title_widget.update("")
            definition_widget.update("No projects are available.")
            meta_widget.update("")
            return

        if snapshot.catalog is None:
            title_widget.update("")
            definition_widget.update("")
            if snapshot.diagnostics:
                meta_widget.update(
                    build_diagnostics_message(snapshot.diagnostics, accent=self._accent)
                )
            else:
                meta_widget.update(
                    build_empty_project_message(
                        snapshot.project.display_name, accent=self._accent
                    )
                )
            return

        entry = self._selected_entry()
        if entry is None:
            title_widget.update("")
            definition_widget.update("")
            if self._filter_text:
                meta_widget.update(build_no_match_message(self._filter_text))
            else:
                meta_widget.update("")
            return

        project_name = snapshot.project.display_name
        title_widget.update(
            build_definition_card_title(
                entry, project_name=project_name, accent=self._accent
            )
        )
        definition_widget.update(glossary_definition_markdown(snapshot.catalog, entry))
        outbound = self._chip_entries[: self._chip_outbound_count]
        inbound = self._chip_entries[self._chip_outbound_count :]
        focused_relation_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        meta_widget.update(
            build_definition_card_meta(
                snapshot.catalog,
                entry,
                project_name=project_name,
                accent=self._accent,
                outbound=outbound,
                inbound=inbound,
                focused_relation_number=focused_relation_number,
            )
        )

    # --- selection helpers ------------------------------------------------

    def _term_list(self) -> OptionList:
        return self.query_one(f"#{_TERM_LIST_ID}", OptionList)

    def _filter_input(self) -> _GlossaryFilterInput:
        return self.query_one(f"#{_FILTER_INPUT_ID}", _GlossaryFilterInput)

    def _current_term_row(self) -> int:
        option_list = self._term_list()
        if option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._entries) - 1)))

    def _selected_entry(self) -> GlossaryEntry | None:
        if not self._entries:
            return None
        row = self._current_term_row()
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != _TERM_LIST_ID:
            return
        idx = event.option_index
        if not 0 <= idx < len(self._entries):
            return
        current_idx = self._current_term_row()
        if not 0 <= current_idx < len(self._entries):
            return
        identity = self._entries[idx].term
        current_identity = self._entries[current_idx].term
        if self._selection_guard.should_ignore(
            identity, idx, current_identity=current_identity, current_row=current_idx
        ):
            return
        self._current_term = identity
        self._refresh_relations_for_current_entry()
        self._update_footer()
        if self._debouncer is not None:
            self._debouncer.schedule(self._render_definition_card)
        else:
            self._render_definition_card()

    # --- term navigation ----------------------------------------------

    def action_next_term(self) -> None:
        if self._entries:
            self._term_list().action_cursor_down()

    def action_prev_term(self) -> None:
        if self._entries:
            self._term_list().action_cursor_up()

    def action_first_term(self) -> None:
        if self._entries:
            self._term_list().highlighted = 0

    def action_last_term(self) -> None:
        if self._entries:
            self._term_list().highlighted = len(self._entries) - 1

    def action_scroll_definition_down(self) -> None:
        scroll = self.query_one("#glossary-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_definition_up(self) -> None:
        scroll = self.query_one("#glossary-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    # --- filter -------------------------------------------------------

    def action_filter_terms(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = True
        filter_input.value = self._filter_text
        filter_input.focus()

    def action_toggle_definition_filter(self) -> None:
        self._apply_filter(self._filter_text, definitions=not self._filter_definitions)

    def _close_filter(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = False
        self._term_list().focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._apply_filter(event.value, definitions=self._filter_definitions)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._close_filter()

    # --- project cycling ------------------------------------------------

    def action_next_project(self) -> None:
        self._cycle_project(1)

    def action_prev_project(self) -> None:
        self._cycle_project(-1)

    def _cycle_project(self, delta: int) -> None:
        if self._loading or len(self._ring) <= 1:
            return
        if self._snapshot is not None:
            self._project_selection_memory[self._snapshot.project.key] = (
                self._current_term or ""
            )
        self._project_index = (self._project_index + delta) % len(self._ring)
        self._filter_input().value = ""
        self._filter_input().display = False
        self._trail = []
        self._start_project_load()

    def action_refresh(self) -> None:
        if self._loading or not self._ring:
            return
        invalidate_glossary_project(self._ring[self._project_index].key)
        self._start_project_load()

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

    # --- relation travel --------------------------------------------------

    def _refresh_relations_for_current_entry(self) -> None:
        """Recompute this entry's chip list and reset the chip cursor.

        Called whenever the selected term changes, so the chip cursor never
        survives a jump to a different entry's relations.
        """
        self._chip_cursor = None
        entry = self._selected_entry()
        if entry is None or self._snapshot is None or self._snapshot.catalog is None:
            self._chip_entries = ()
            self._chip_outbound_count = 0
            return
        outbound, inbound = glossary_entry_relations(self._snapshot, entry)
        self._chip_entries = outbound + inbound
        self._chip_outbound_count = len(outbound)

    def action_next_relation(self) -> None:
        if not self._chip_entries:
            return
        if self._chip_cursor is None:
            self._chip_cursor = 0
        else:
            self._chip_cursor = (self._chip_cursor + 1) % len(self._chip_entries)
        self._render_definition_card()
        self._update_footer()

    def action_prev_relation(self) -> None:
        if not self._chip_entries:
            return
        if self._chip_cursor is None:
            self._chip_cursor = len(self._chip_entries) - 1
        else:
            self._chip_cursor = (self._chip_cursor - 1) % len(self._chip_entries)
        self._render_definition_card()
        self._update_footer()

    def action_follow_relation(self) -> None:
        self._follow_relation_index(
            self._chip_cursor if self._chip_cursor is not None else 0
        )

    def action_follow_relation_number(self, number: int) -> None:
        self._follow_relation_index(number - 1)

    def _follow_relation_index(self, index: int) -> None:
        if not self._chip_entries or not 0 <= index < len(self._chip_entries):
            return
        self._travel_forward(self._chip_entries[index].term)

    def _travel_forward(self, target_term: str) -> None:
        if self._current_term is None or target_term == self._current_term:
            return
        self._trail.append(self._current_term)
        if len(self._trail) > _MAX_TRAIL_LENGTH:
            del self._trail[0]
        self._land_on_term(target_term)

    def action_travel_back(self) -> None:
        while self._trail:
            term = self._trail.pop()
            if any(entry.term == term for entry in self._all_entries):
                self._land_on_term(term)
                return

    def _land_on_term(self, term: str) -> None:
        if self._select_term_by_identity(term):
            self._render_definition_card()
            self._update_footer()
        else:
            self.notify(f'Filter cleared to show "{term}"')
            self._filter_input().value = ""
            self._apply_filter("", definitions=False, preferred_term=term)
        self.query_one("#glossary-panel-detail", VerticalScroll).scroll_home(
            animate=False
        )

    def _select_term_by_identity(self, term: str) -> bool:
        """Move the term-list highlight to *term* if it is currently visible."""
        option_list = self._term_list()
        for row, entry in enumerate(self._entries):
            if entry.term == term:
                self._selection_guard.prepare(term, row)
                option_list.highlighted = row
                self._current_term = term
                self._refresh_relations_for_current_entry()
                return True
        return False


__all__ = ["GlossaryPanel"]
