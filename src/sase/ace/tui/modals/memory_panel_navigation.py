"""Note, filter, and scope navigation for the Memory panel.

The movement axes the note rail itself owns: cursor motion plus body
scrolling, the inline filter box, and ``p``/``P``/``ctrl+p`` scope movement
with its refresh. Parent/child chip travel is the fourth axis and lives
in :mod:`sase.ace.tui.modals.memory_panel_travel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widgets import Input

from sase.ace.tui.memory_panel_catalog import invalidate_memory_scope

from .memory_panel_state import _FILTER_INPUT_ID

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.memory_panel_catalog import (
        MemoryRailNode,
        MemoryScopeRef,
        MemoryScopeSnapshot,
    )
    from sase.memory.notes import MemoryNote
else:
    _MixinBase = object


class MemoryPanelNavigationMixin(_MixinBase):
    """Note cursor, body scrolling, filtering, and scope cycling/picking."""

    if TYPE_CHECKING:
        _current_note: str | None
        _filter_bodies: bool
        _filter_text: str
        _loading: bool
        _rows: tuple[MemoryRailNode, ...]
        _ring: tuple[MemoryScopeRef, ...]
        _scope_index: int
        _scope_selection_memory: dict[str, str]
        _snapshot: MemoryScopeSnapshot | None
        _trail: list[str]
        _chip_cursor: int | None
        _chip_notes: tuple[MemoryNote, ...]
        _chip_parent_count: int

        def _apply_filter(
            self,
            pattern: str,
            *,
            include_bodies: bool,
            preferred_note: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _note_list(self) -> OptionList: ...

        def _start_scope_load(self) -> None: ...

        def _start_scope_picker_load(self) -> None: ...

    # --- note navigation ------------------------------------------------

    def action_next_note(self) -> None:
        if self._rows:
            self._note_list().action_cursor_down()

    def action_prev_note(self) -> None:
        if self._rows:
            self._note_list().action_cursor_up()

    def action_first_note(self) -> None:
        if self._rows:
            self._note_list().highlighted = 0

    def action_last_note(self) -> None:
        if self._rows:
            self._note_list().highlighted = len(self._rows) - 1

    def action_scroll_body_down(self) -> None:
        scroll = self.query_one("#memory-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_body_up(self) -> None:
        scroll = self.query_one("#memory-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    # --- filter -----------------------------------------------------------

    def action_filter_notes(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = True
        filter_input.value = self._filter_text
        filter_input.focus()

    def action_toggle_body_filter(self) -> None:
        self._apply_filter(self._filter_text, include_bodies=not self._filter_bodies)

    def _close_filter(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = False
        self._note_list().focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._apply_filter(event.value, include_bodies=self._filter_bodies)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._close_filter()

    # --- scope cycling and picking ----------------------------------------

    def action_next_scope(self) -> None:
        self._cycle_scope(1)

    def action_prev_scope(self) -> None:
        self._cycle_scope(-1)

    def action_pick_scope(self) -> None:
        if self._loading or not self._ring:
            return
        self._start_scope_picker_load()

    def _cycle_scope(self, delta: int) -> None:
        if self._loading or len(self._ring) <= 1:
            return
        if self._snapshot is not None:
            self._scope_selection_memory[self._snapshot.scope.key] = (
                self._current_note or ""
            )
        self._scope_index = (self._scope_index + delta) % len(self._ring)
        self._filter_input().value = ""
        self._filter_input().display = False
        self._trail = []
        self._chip_notes = ()
        self._chip_parent_count = 0
        self._chip_cursor = None
        self._start_scope_load()

    def action_refresh(self) -> None:
        if self._loading or not self._ring:
            return
        invalidate_memory_scope(self._ring[self._scope_index].key)
        self._start_scope_load()


__all__ = ["MemoryPanelNavigationMixin"]
