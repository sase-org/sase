"""Relation-chip travel for the Snippets panel.

The panel's second navigation axis: the numbered CALLS / CALLED BY chip
cursor, follow-by-digit jumps, and the bounded breadcrumb trail that
``travel back`` walks. Missing and cyclic calls stay out of the chip list
so they cannot be followed. Chip *rendering* lives in
:mod:`sase.ace.tui.modals.snippets_panel_view`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll

from sase.ace.tui.snippets_panel_catalog import snippet_entry_relations

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
    from textual.widgets import Input, OptionList

    from sase.ace.tui.snippets_panel_catalog import SnippetProjectSnapshot
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
    from sase.snippet.models import SnippetEntry
else:
    _MixinBase = object

_MAX_TRAIL_LENGTH = 32


class SnippetsPanelTravelMixin(_MixinBase):
    """Chip cursor, follow/back travel, and the breadcrumb trail."""

    if TYPE_CHECKING:
        _all_entries: tuple[SnippetEntry, ...]
        _chip_cursor: int | None
        _chip_entries: tuple[SnippetEntry, ...]
        _chip_outbound_count: int
        _current_trigger: str | None
        _entries: tuple[SnippetEntry, ...]
        _selection_guard: ProgrammaticSelectionGuard
        _snapshot: SnippetProjectSnapshot | None
        _trail: list[str]

        def _apply_filter(
            self,
            pattern: str,
            *,
            bodies: bool,
            preferred_trigger: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _render_snippet_card(self) -> None: ...

        def _selected_entry(self) -> SnippetEntry | None: ...

        def _trigger_list(self) -> OptionList: ...

        def _update_footer(self) -> None: ...

        def notify(self, message: str, **kwargs: object) -> None: ...

    def _refresh_relations_for_current_entry(self) -> None:
        """Recompute this entry's chip list and reset the chip cursor.

        Called whenever the selected trigger changes, so the chip cursor never
        survives a jump to a different entry's relations.
        """
        self._chip_cursor = None
        entry = self._selected_entry()
        if entry is None or self._snapshot is None or self._snapshot.catalog is None:
            self._chip_entries = ()
            self._chip_outbound_count = 0
            return
        outbound, inbound = snippet_entry_relations(self._snapshot, entry)
        self._chip_entries = outbound + inbound
        self._chip_outbound_count = len(outbound)

    def action_next_relation(self) -> None:
        if not self._chip_entries:
            return
        if self._chip_cursor is None:
            self._chip_cursor = 0
        else:
            self._chip_cursor = (self._chip_cursor + 1) % len(self._chip_entries)
        self._render_snippet_card()
        self._update_footer()

    def action_prev_relation(self) -> None:
        if not self._chip_entries:
            return
        if self._chip_cursor is None:
            self._chip_cursor = len(self._chip_entries) - 1
        else:
            self._chip_cursor = (self._chip_cursor - 1) % len(self._chip_entries)
        self._render_snippet_card()
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
        self._travel_forward(self._chip_entries[index].trigger)

    def _travel_forward(self, target_trigger: str) -> None:
        if self._current_trigger is None or target_trigger == self._current_trigger:
            return
        self._trail.append(self._current_trigger)
        if len(self._trail) > _MAX_TRAIL_LENGTH:
            del self._trail[0]
        self._land_on_trigger(target_trigger)

    def action_travel_back(self) -> None:
        while self._trail:
            trigger = self._trail.pop()
            if any(entry.trigger == trigger for entry in self._all_entries):
                self._land_on_trigger(trigger)
                return

    def _land_on_trigger(self, trigger: str) -> None:
        if self._select_trigger_by_identity(trigger):
            self._render_snippet_card()
            self._update_footer()
        else:
            self.notify(f'Filter cleared to show "{trigger}"')
            self._filter_input().value = ""
            self._apply_filter("", bodies=False, preferred_trigger=trigger)
        self.query_one("#snippets-panel-detail", VerticalScroll).scroll_home(
            animate=False
        )

    def _select_trigger_by_identity(self, trigger: str) -> bool:
        """Move the trigger-list highlight to *trigger* if it is visible."""
        option_list = self._trigger_list()
        for row, entry in enumerate(self._entries):
            if entry.trigger == trigger:
                self._selection_guard.prepare(trigger, row)
                option_list.highlighted = row
                self._current_trigger = trigger
                self._refresh_relations_for_current_entry()
                return True
        return False


__all__ = ["SnippetsPanelTravelMixin"]
