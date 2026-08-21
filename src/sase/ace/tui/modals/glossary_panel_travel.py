"""Relation-chip travel for the Glossary panel.

The panel's second navigation axis: the numbered SEE ALSO / REFERENCED BY chip
cursor, ``>`` then digit jumps, and the bounded breadcrumb trail that `travel
back` walks. Chip *rendering* lives in
:mod:`sase.ace.tui.modals.glossary_panel_view`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll

from sase.ace.tui.glossary_panel_catalog import glossary_entry_relations

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
    from textual.widgets import Input, OptionList

    from sase.ace.tui.glossary_panel_catalog import GlossaryProjectSnapshot
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
    from sase.core.glossary_facade import GlossaryEntry
else:
    _MixinBase = object

_MAX_TRAIL_LENGTH = 32


class GlossaryPanelTravelMixin(_MixinBase):
    """Chip cursor, follow/back travel, and the breadcrumb trail."""

    if TYPE_CHECKING:
        _all_entries: tuple[GlossaryEntry, ...]
        _chip_cursor: int | None
        _chip_entries: tuple[GlossaryEntry, ...]
        _chip_outbound_count: int
        _current_term: str | None
        _entries: tuple[GlossaryEntry, ...]
        _selection_guard: ProgrammaticSelectionGuard
        _snapshot: GlossaryProjectSnapshot | None
        _trail: list[str]

        def _apply_filter(
            self,
            pattern: str,
            *,
            definitions: bool,
            preferred_term: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _record_session_selection(self) -> None: ...

        def _render_definition_card(self) -> None: ...

        def _selected_entry(self) -> GlossaryEntry | None: ...

        def _term_list(self) -> OptionList: ...

        def _update_footer(self) -> None: ...

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
                self._record_session_selection()
                self._refresh_relations_for_current_entry()
                return True
        return False


__all__ = ["GlossaryPanelTravelMixin"]
