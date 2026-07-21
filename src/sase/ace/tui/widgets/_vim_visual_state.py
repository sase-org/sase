"""Vim visual-mode selection and range state for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from textual.document._document import Selection

from sase.ace.tui.widgets._vim_normal_ops import VimNormalOpsMixin
from sase.ace.tui.widgets._vim_normal_state import VisualMutation
from sase.ace.tui.widgets._vim_registers import VimRegister

VisualKind = Literal["charwise", "linewise"]


class VimVisualStateMixin(VimNormalOpsMixin):
    """Mixin providing vim visual-mode selection and range state."""

    if TYPE_CHECKING:
        _vim_mode: str
        _pending_keys: str
        _count_prefix: str
        _pending_count: int | None
        _pending_operator: str
        _pending_operator_count: int
        _mutation_key_buffer: list[str]
        _last_mutation_keys: list[str]
        _last_mutation_count: int
        _last_mutation_insert: str | None
        _last_visual_mutation: VisualMutation | None
        _replaying_dot: bool
        _last_char_search: tuple[str, str] | None
        _vim_register: VimRegister
        _visual_anchor: tuple[int, int] | None
        _visual_cursor: tuple[int, int] | None
        _pending_visual_surround_range: (
            tuple[str, tuple[int, int], tuple[int, int], int] | None
        )

        def _update_vim_mode_display(self, indicator: str = "") -> None: ...

        def _enter_normal_mode(self) -> None: ...

        def _enter_insert_mode(self) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...
        def _sync_vim_cursor_class(self) -> None: ...

        def _execute_linewise_transform_operator(
            self,
            first_row: int,
            last_row: int,
            op: str,
            *,
            units: int = 1,
        ) -> None: ...

    def _enter_visual_mode(self, kind: VisualKind) -> None:
        """Switch to vim VISUAL or V-LINE mode."""
        self._pending_keys = ""
        self._pending_count = None
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_visual_surround_range = None
        self._count_prefix = ""
        self._mutation_key_buffer.clear()
        self._visual_anchor = self.cursor_location
        self._visual_cursor = self.cursor_location
        self._vim_mode = "visual" if kind == "charwise" else "visual_line"
        self.read_only = True
        self._sync_vim_cursor_class()
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        self._update_visual_selection()
        self._update_visual_display()

    def _clear_visual_state(
        self,
        cursor: tuple[int, int] | None = None,
    ) -> None:
        """Clear visual selection state and collapse TextArea selection."""
        if cursor is None:
            cursor = (
                self.cursor_location if self.selection.is_empty else self._visual_cursor
            )
        if cursor is None:
            cursor = self.cursor_location
        cursor = self._clamp_visual_location(cursor)
        self._visual_anchor = None
        self._visual_cursor = None
        self.selection = Selection.cursor(cursor)

    def _switch_visual_kind(self, kind: VisualKind) -> None:
        """Switch an active visual selection between charwise and linewise."""
        self._vim_mode = "visual" if kind == "charwise" else "visual_line"
        self._sync_vim_cursor_class()
        self._update_visual_selection()
        self._update_visual_display()

    def _visual_kind(self) -> VisualKind:
        """Return the current visual selection kind."""
        return "linewise" if self._vim_mode == "visual_line" else "charwise"

    def _visual_locations(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return ``(anchor, cursor)`` for the active visual selection."""
        anchor = self._visual_anchor
        cursor = self._visual_cursor
        if anchor is None or cursor is None:
            location = self.cursor_location
            return (location, location)
        return (anchor, cursor)

    def _clamp_visual_location(self, location: tuple[int, int]) -> tuple[int, int]:
        """Clamp a document location to the current document bounds."""
        row, col = location
        row = max(0, min(row, self.document.line_count - 1))
        line = self.document.get_line(row)
        return (row, max(0, min(col, len(line))))

    def _location_after_visual_char(self, location: tuple[int, int]) -> tuple[int, int]:
        """Return the exclusive end location for a charwise visual cursor."""
        row, col = self._clamp_visual_location(location)
        line = self.document.get_line(row)
        if col < len(line):
            return (row, col + 1)
        return (row, col)

    def _location_before_exclusive_end(
        self,
        end: tuple[int, int],
        fallback: tuple[int, int],
    ) -> tuple[int, int]:
        """Convert an exclusive range end to an inclusive visual cursor."""
        end = self._clamp_visual_location(end)
        if end <= fallback:
            return fallback
        row, col = end
        if col > 0:
            return (row, col - 1)
        if row > 0:
            prev = row - 1
            return (prev, len(self.document.get_line(prev)))
        return fallback

    def _charwise_visual_range(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return the normalized exclusive range for charwise visual mode."""
        anchor, cursor = self._visual_locations()
        anchor = self._clamp_visual_location(anchor)
        cursor = self._clamp_visual_location(cursor)
        if anchor <= cursor:
            return (anchor, self._location_after_visual_char(cursor))
        return (cursor, self._location_after_visual_char(anchor))

    def _linewise_visual_rows(self) -> tuple[int, int]:
        """Return the first and last selected rows for linewise visual mode."""
        anchor, cursor = self._visual_locations()
        first = min(anchor[0], cursor[0])
        last = max(anchor[0], cursor[0])
        return (
            max(0, min(first, self.document.line_count - 1)),
            max(0, min(last, self.document.line_count - 1)),
        )

    def _linewise_visual_range(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return the normalized exclusive range for V-LINE mode."""
        first, last = self._linewise_visual_rows()
        start = (first, 0)
        if last >= self.document.line_count - 1:
            end = (last, len(self.document.get_line(last)))
        else:
            end = (last + 1, 0)
        return (start, end)

    def _update_visual_selection(self) -> None:
        """Mirror visual state into TextArea's native selection."""
        anchor, cursor = self._visual_locations()
        anchor = self._clamp_visual_location(anchor)
        cursor = self._clamp_visual_location(cursor)
        self._visual_anchor = anchor
        self._visual_cursor = cursor

        if self._visual_kind() == "linewise":
            start, end = self._linewise_visual_range()
            if anchor[0] <= cursor[0]:
                self.selection = Selection(start, end)
            else:
                self.selection = Selection(end, start)
            return

        start, end = self._charwise_visual_range()
        if anchor <= cursor:
            self.selection = Selection(start, end)
        else:
            self.selection = Selection(end, start)

    def _update_visual_display(self) -> None:
        """Refresh the mode display for visual mode via the host hook.

        The active visual kind is read from ``_vim_mode`` by the host hook, so
        only the pending count prefix needs to be passed as the indicator.
        """
        indicator = (
            "S" if self._pending_keys == "visual-surround" else self._count_prefix
        )
        self._update_vim_mode_display(indicator)

    def _move_visual_cursor(self, location: tuple[int, int]) -> None:
        """Move the visual cursor and extend the active selection."""
        self._visual_cursor = self._clamp_visual_location(location)
        self._update_visual_selection()

    def _select_visual_char_range(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        """Replace the active selection with a charwise exclusive range."""
        start = self._clamp_visual_location(start)
        cursor = self._location_before_exclusive_end(end, start)
        self._vim_mode = "visual"
        self._sync_vim_cursor_class()
        self._visual_anchor = start
        self._visual_cursor = cursor
        self._update_visual_selection()
        self._update_visual_display()

    def _select_visual_line_range(self, first_row: int, last_row: int) -> None:
        """Replace the active selection with a linewise range."""
        first_row = max(0, min(first_row, self.document.line_count - 1))
        last_row = max(0, min(last_row, self.document.line_count - 1))
        self._vim_mode = "visual_line"
        self._sync_vim_cursor_class()
        self._visual_anchor = (first_row, 0)
        self._visual_cursor = (last_row, 0)
        self._update_visual_selection()
        self._update_visual_display()

    def _swap_visual_ends(self) -> None:
        """Swap the visual anchor and cursor ends (vim ``o``)."""
        anchor, cursor = self._visual_locations()
        self._visual_anchor = cursor
        self._visual_cursor = anchor
        self._update_visual_selection()

    def _collapse_visual_before_operator(self) -> tuple[int, int]:
        """Collapse native selection before mutating the document."""
        cursor = self._visual_cursor or self.cursor_location
        cursor = self._clamp_visual_location(cursor)
        self.selection = Selection.cursor(cursor)
        return cursor


__all__ = ["VisualKind", "VimVisualStateMixin"]
