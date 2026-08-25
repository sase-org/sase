"""Snapshot, filter, and term-selection state for the Glossary panel.

This is the panel's core state machine: it turns a loaded project snapshot
into the filtered, alphabetically sorted term list, keeps the ``OptionList``
highlight anchored to the same term across reloads and filter edits, and
answers "which entry is selected?" for every other mixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.util.selection import restore_selection_by_identity
from sase.memory.web.text_filter import filter_glossary_entries

from .glossary_panel_rendering import build_term_row_text, sorted_glossary_entries

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.ace.tui.glossary_panel_catalog import (
        GlossaryProjectRef,
        GlossaryProjectSnapshot,
    )
    from sase.ace.tui.util.debounce import DetailPanelDebouncer
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
    from sase.core.glossary_facade import GlossaryEntry

    from .catalog_pane_contract import CatalogPaneSession
else:
    _MixinBase = object

_TERM_LIST_ID = "glossary-panel-terms"
_FILTER_INPUT_ID = "glossary-panel-filter"


class GlossaryPanelStateMixin(_MixinBase):
    """Snapshot application, filtering, and selection for :class:`GlossaryPane`."""

    if TYPE_CHECKING:
        _all_entries: tuple[GlossaryEntry, ...]
        _current_term: str | None
        _debouncer: DetailPanelDebouncer | None
        _entries: tuple[GlossaryEntry, ...]
        _filter_definitions: bool
        _filter_text: str
        _project_index: int
        _ring: tuple[GlossaryProjectRef, ...]
        _selection_guard: ProgrammaticSelectionGuard
        _session: CatalogPaneSession | None
        _snapshot: GlossaryProjectSnapshot | None

        def _refresh_relations_for_current_entry(self) -> None: ...

        def _render_definition_card(self) -> None: ...

        def _resize_term_rail(self) -> None: ...

        def _update_footer(self) -> None: ...

        def _update_header(self) -> None: ...

    def _apply_snapshot(
        self, snapshot: GlossaryProjectSnapshot | None, *, preferred_term: str | None
    ) -> None:
        self._snapshot = snapshot
        self._all_entries = sorted_glossary_entries(
            snapshot.catalog if snapshot is not None else None
        )
        self._resize_term_rail()
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
        self._record_session_selection()
        self._refresh_relations_for_current_entry()
        self._render_definition_card()

    # --- selection helpers ------------------------------------------------

    def _term_list(self) -> OptionList:
        return self.query_one(f"#{_TERM_LIST_ID}", OptionList)

    def _filter_input(self) -> Input:
        return self.query_one(f"#{_FILTER_INPUT_ID}", Input)

    def _current_term_row(self) -> int:
        option_list = self._term_list()
        if option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._entries) - 1)))

    def _record_session_selection(self) -> None:
        """Write the live project and term through the injected session."""
        session = self._session
        if session is None:
            return
        snapshot = self._snapshot
        if snapshot is not None:
            session.record_scope(snapshot.project.key)
        elif self._ring:
            session.record_scope(self._ring[self._project_index].key)
        session.record_entry(self._current_term)

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
        self._record_session_selection()
        self._refresh_relations_for_current_entry()
        self._update_footer()
        if self._debouncer is not None:
            self._debouncer.schedule(self._render_definition_card)
        else:
            self._render_definition_card()


__all__ = ["GlossaryPanelStateMixin"]
