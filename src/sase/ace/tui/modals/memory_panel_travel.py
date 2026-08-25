"""Parent/child chip travel for the Memory panel.

The panel's second navigation axis: the numbered PARENT / CHILDREN chip
cursor, ``>`` then digit jumps, and the bounded breadcrumb trail that
`travel back` walks. Chip *rendering* lives in
:mod:`sase.ace.tui.modals.memory_panel_view`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.containers import VerticalScroll

from sase.ace.tui.memory_panel_catalog import memory_rail_node_relations

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
    from textual.widgets import Input, OptionList

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode, MemoryScopeSnapshot
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
    from sase.memory.notes import MemoryNote
else:
    _MixinBase = object

_MAX_TRAIL_LENGTH = 32


class MemoryPanelTravelMixin(_MixinBase):
    """Chip cursor, follow/back travel, and the breadcrumb trail."""

    if TYPE_CHECKING:
        _all_rows: tuple[MemoryRailNode, ...]
        _chip_cursor: int | None
        _chip_notes: tuple[MemoryNote, ...]
        _chip_parent_count: int
        _current_note: str | None
        _rows: tuple[MemoryRailNode, ...]
        _selection_guard: ProgrammaticSelectionGuard
        _snapshot: MemoryScopeSnapshot | None
        _trail: list[str]

        def _apply_filter(
            self,
            pattern: str,
            *,
            include_bodies: bool,
            preferred_note: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _ensure_strand_read_for_current_selection(self) -> None: ...

        def _render_note_card(self) -> None: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

        def _note_list(self) -> OptionList: ...

        def _update_footer(self) -> None: ...

    def _refresh_links_for_current_note(self) -> None:
        """Recompute this note's chip list and reset the chip cursor.

        Called whenever the selected note changes, so the chip cursor never
        survives a jump to a different note's parent/child links.
        """
        self._chip_cursor = None
        node = self._selected_row()
        if node is None or self._snapshot is None:
            self._chip_notes = ()
            self._chip_parent_count = 0
            return
        parent, children = memory_rail_node_relations(self._snapshot, node)
        self._chip_notes = parent + children
        self._chip_parent_count = len(parent)

    def action_next_link(self) -> None:
        if not self._chip_notes:
            return
        if self._chip_cursor is None:
            self._chip_cursor = 0
        else:
            self._chip_cursor = (self._chip_cursor + 1) % len(self._chip_notes)
        self._render_note_card()
        self._update_footer()

    def action_prev_link(self) -> None:
        if not self._chip_notes:
            return
        if self._chip_cursor is None:
            self._chip_cursor = len(self._chip_notes) - 1
        else:
            self._chip_cursor = (self._chip_cursor - 1) % len(self._chip_notes)
        self._render_note_card()
        self._update_footer()

    def action_follow_link(self) -> None:
        self._follow_link_index(
            self._chip_cursor if self._chip_cursor is not None else 0
        )

    def action_follow_link_number(self, number: int) -> None:
        self._follow_link_index(number - 1)

    def _follow_link_index(self, index: int) -> None:
        if not self._chip_notes or not 0 <= index < len(self._chip_notes):
            return
        self._travel_forward(self._chip_notes[index].relative_path)

    def _travel_forward(self, target_note: str) -> None:
        if self._current_note is None or target_note == self._current_note:
            return
        self._trail.append(self._current_note)
        if len(self._trail) > _MAX_TRAIL_LENGTH:
            del self._trail[0]
        self._land_on_identity(target_note)

    def action_travel_back(self) -> None:
        while self._trail:
            identity = self._trail.pop()
            if any(node.identity == identity for node in self._all_rows):
                self._land_on_identity(identity)
                return

    def _land_on_identity(self, identity: str) -> None:
        if self._select_note_by_identity(identity):
            self._render_note_card()
            self._update_footer()
        else:
            stem = Path(identity).stem
            self.notify(f'Filter cleared to show "{stem}"')
            self._filter_input().value = ""
            self._apply_filter("", include_bodies=False, preferred_note=identity)
        self.query_one("#memory-panel-detail", VerticalScroll).scroll_home(
            animate=False
        )

    def _land_on_note(self, note_path: str) -> None:
        self._land_on_identity(note_path)

    def _select_note_by_identity(self, identity: str) -> bool:
        """Move the rail highlight to *identity* if it is currently visible."""
        option_list = self._note_list()
        for row, node in enumerate(self._rows):
            if node.identity == identity:
                self._selection_guard.prepare(identity, row)
                option_list.highlighted = row
                self._current_note = identity
                self._refresh_links_for_current_note()
                self._ensure_strand_read_for_current_selection()
                return True
        return False


__all__ = ["MemoryPanelTravelMixin"]
