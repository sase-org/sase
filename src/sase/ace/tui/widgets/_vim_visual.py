"""Vim visual-mode key handling for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from textual.document._document import Selection
from textual.events import Key

from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.widgets._vim_motions import (
    find_a_WORD,
    find_a_word,
    find_char_backward,
    find_char_forward,
    find_inner_WORD,
    find_inner_word,
    find_next_WORD_end,
    find_next_WORD_start,
    find_next_word_end,
    find_next_word_start,
    find_prev_WORD_start,
    find_prev_word_start,
)
from sase.ace.tui.widgets._vim_normal_ops import VimNormalOpsMixin
from sase.ace.tui.widgets._vim_registers import VimRegister, first_non_blank_col

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


VisualKind = Literal["charwise", "linewise"]


class VimVisualModeMixin(VimNormalOpsMixin):
    """Mixin providing vim visual-mode key handling."""

    if TYPE_CHECKING:
        _vim_mode: str
        _pending_keys: str
        _count_prefix: str
        _pending_count: int | None
        _pending_operator: str
        _pending_operator_count: int
        _mutation_key_buffer: list[str]
        _last_char_search: tuple[str, str] | None
        _vim_register: VimRegister
        _visual_anchor: tuple[int, int] | None
        _visual_cursor: tuple[int, int] | None

        def _find_prompt_bar(self) -> Any: ...

        def _enter_normal_mode(self) -> None: ...

        def _enter_insert_mode(self) -> None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

    def _enter_visual_mode(self, kind: VisualKind) -> None:
        """Switch to vim VISUAL or V-LINE mode."""
        self._pending_keys = ""
        self._pending_count = None
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._count_prefix = ""
        self._mutation_key_buffer.clear()
        self._visual_anchor = self.cursor_location
        self._visual_cursor = self.cursor_location
        self._vim_mode = "visual" if kind == "charwise" else "visual_line"
        self.read_only = True
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
        """Update border title/subtitle for visual mode."""
        bar = self._find_prompt_bar()
        if not bar:
            return
        title_mode = "[V-LINE]" if self._visual_kind() == "linewise" else "[VISUAL]"
        bar.border_title = f"{bar._base_title} {title_mode}"
        subtitle = "[Esc] normal  [o] swap ends  [^C] cancel"
        if self._count_prefix:
            subtitle += f"  {self._count_prefix}"
        setter = getattr(bar, "set_prompt_mode_subtitle", None)
        if callable(setter):
            setter(subtitle)
        else:
            bar.border_subtitle = subtitle

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
        self._visual_anchor = start
        self._visual_cursor = cursor
        self._update_visual_selection()
        self._update_visual_display()

    def _select_visual_line_range(self, first_row: int, last_row: int) -> None:
        """Replace the active selection with a linewise range."""
        first_row = max(0, min(first_row, self.document.line_count - 1))
        last_row = max(0, min(last_row, self.document.line_count - 1))
        self._vim_mode = "visual_line"
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

    def _store_visual_register(self, text: str, kind: VisualKind) -> None:
        """Store selected text in the unnamed register and system clipboard."""
        self._store_vim_register(text, kind)
        if text:
            copy_to_system_clipboard(text)

    def _visual_selected_text(self) -> tuple[str, VisualKind]:
        """Return selected text and register kind for the current visual mode."""
        if self._visual_kind() == "linewise":
            first, last = self._linewise_visual_rows()
            lines = [self.document.get_line(row) for row in range(first, last + 1)]
            return ("\n".join(lines), "linewise")
        start, end = self._charwise_visual_range()
        return (self._get_text_in_range(start, end), "charwise")

    def _linewise_replacement_payload(self, text: str) -> str:
        """Return replacement text for a linewise visual range."""
        _first, last = self._linewise_visual_rows()
        if text and last < self.document.line_count - 1:
            return text + "\n"
        return text

    def _apply_visual_operator(self, op: str) -> None:
        """Apply a visual operator to the active selection."""
        kind = self._visual_kind()
        self._collapse_visual_before_operator()
        if kind == "linewise":
            first, last = self._linewise_visual_rows()
            self._execute_linewise_operator(first, last, op)
            if op == "c":
                return
            if op == "y":
                self.selection = Selection.cursor((first, 0))
            self._enter_normal_mode()
            return

        start, end = self._charwise_visual_range()
        self._execute_charwise_operator(start, end, op)
        if op == "c":
            return
        self._enter_normal_mode()

    def _replace_visual_selection_with_register(self, count: int) -> None:
        """Replace the active visual selection with the unnamed register."""
        count = max(1, count)
        register = self._vim_register
        selected_text, selected_kind = self._visual_selected_text()
        kind = self._visual_kind()
        self._collapse_visual_before_operator()
        self._store_visual_register(selected_text, selected_kind)

        was_readonly = self.read_only
        self.read_only = False
        if kind == "linewise":
            start, end = self._linewise_visual_range()
            insert = "\n".join(register.text.split("\n") * count)
            payload = self._linewise_replacement_payload(insert)
            self._record_mutation()
            self._replace_via_keyboard(payload, start, end)
            self.read_only = was_readonly
            first_line = insert.split("\n", 1)[0] if insert else ""
            cursor = (start[0], first_non_blank_col(first_line))
            self.selection = Selection.cursor(cursor)
            self._enter_normal_mode()
            return

        start, end = self._charwise_visual_range()
        insert = register.text * count
        self._record_mutation()
        self._replace_via_keyboard(insert, start, end)
        self.read_only = was_readonly
        cursor = self._last_char_location_after_insert(start, insert)
        self.selection = Selection.cursor(cursor)
        self._enter_normal_mode()

    def _toggle_visual_case(self) -> None:
        """Toggle case over the active visual selection."""
        selected_text, selected_kind = self._visual_selected_text()
        if not selected_text:
            self._clear_visual_state()
            self._enter_normal_mode()
            return
        kind = self._visual_kind()
        self._collapse_visual_before_operator()
        self._store_visual_register(selected_text, selected_kind)
        was_readonly = self.read_only
        self.read_only = False
        if kind == "linewise":
            start, end = self._linewise_visual_range()
            replacement = self._linewise_replacement_payload(selected_text.swapcase())
        else:
            start, end = self._charwise_visual_range()
            replacement = selected_text.swapcase()
        self._record_mutation()
        self._replace_via_keyboard(replacement, start, end)
        self.read_only = was_readonly
        self.selection = Selection.cursor(start)
        self._enter_normal_mode()

    def _visual_count(self) -> tuple[bool, int]:
        """Consume and return the current count prefix."""
        has_count = bool(self._count_prefix)
        count = int(self._count_prefix) if self._count_prefix else 1
        self._count_prefix = ""
        self._update_visual_display()
        return (has_count, count)

    def _handle_visual_pending_key(self, key: str) -> bool:
        """Handle a key after a visual pending prefix."""
        pending = self._pending_keys
        self._pending_keys = ""
        pending_count = self._pending_count
        self._pending_count = None
        motion_count = pending_count if pending_count is not None else 1

        if pending == "g" and key == "g":
            target = (
                max(0, min(motion_count - 1, self.document.line_count - 1))
                if pending_count is not None
                else 0
            )
            self._move_visual_cursor((target, 0))
            return True

        if pending in "fFtT":
            self._last_char_search = (pending, key)
            self._execute_visual_char_search(pending, key, motion_count)
            return True

        if pending == "a" and key == "e":
            self._select_visual_line_range(0, self.document.line_count - 1)
            return True

        if pending in "ai" and key in "wW":
            is_inner = pending == "i"
            is_WORD = key == "W"
            row, col = self._visual_cursor or self.cursor_location
            if is_inner:
                if is_WORD:
                    sr, sc, er, ec = find_inner_WORD(
                        self.document, row, col, motion_count
                    )
                else:
                    sr, sc, er, ec = find_inner_word(
                        self.document, row, col, motion_count
                    )
            elif is_WORD:
                sr, sc, er, ec = find_a_WORD(self.document, row, col, motion_count)
            else:
                sr, sc, er, ec = find_a_word(self.document, row, col, motion_count)
            self._select_visual_char_range((sr, sc), (er, ec))
            return True

        return True

    def _execute_visual_char_search(
        self,
        motion: str,
        target_char: str,
        count: int,
        *,
        col_offset: int = 0,
    ) -> bool:
        """Execute a visual f/F/t/T motion."""
        row, col = self._visual_cursor or self.cursor_location
        search_col = col + col_offset
        line = self.document.get_line(row)
        if motion in "ft":
            target_col = find_char_forward(line, search_col, target_char, count)
        else:
            target_col = find_char_backward(line, search_col, target_char, count)
        if target_col is None:
            return False

        if motion == "f":
            self._move_visual_cursor((row, target_col))
        elif motion == "t":
            self._move_visual_cursor((row, max(0, target_col - 1)))
        elif motion == "F":
            self._move_visual_cursor((row, target_col))
        elif motion == "T":
            self._move_visual_cursor((row, min(len(line), target_col + 1)))
        return True

    def _handle_visual_mode_key(self, event: Key) -> bool:
        """Handle a key event in VISUAL or V-LINE mode."""
        key = event.character or event.key

        if event.key == "escape":
            self._pending_keys = ""
            self._pending_count = None
            self._count_prefix = ""
            self._enter_normal_mode()
            return True

        if self._pending_keys:
            return self._handle_visual_pending_key(key)

        if key in "123456789" or (key == "0" and self._count_prefix):
            self._count_prefix += key
            self._update_visual_display()
            return True

        has_count, count = self._visual_count()
        row, col = self._visual_cursor or self.cursor_location
        doc = self.document

        if key == "v":
            if self._visual_kind() == "charwise":
                self._enter_normal_mode()
            else:
                self._switch_visual_kind("charwise")
            return True
        if key == "V":
            if self._visual_kind() == "linewise":
                self._enter_normal_mode()
            else:
                self._switch_visual_kind("linewise")
            return True
        if key == "o":
            self._swap_visual_ends()
            return True

        if key == "h":
            self._move_visual_cursor((row, max(0, col - count)))
            return True
        if key == "l":
            line = doc.get_line(row)
            self._move_visual_cursor((row, min(len(line), col + count)))
            return True
        if key == "j":
            target = min(row + count, doc.line_count - 1)
            self._move_visual_cursor((target, col))
            return True
        if key == "k":
            target = max(row - count, 0)
            self._move_visual_cursor((target, col))
            return True

        if key == "w":
            for _ in range(count):
                row, col = find_next_word_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "W":
            for _ in range(count):
                row, col = find_next_WORD_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "b":
            for _ in range(count):
                row, col = find_prev_word_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "B":
            for _ in range(count):
                row, col = find_prev_WORD_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "e":
            for _ in range(count):
                row, col = find_next_word_end(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "E":
            for _ in range(count):
                row, col = find_next_WORD_end(doc, row, col)
            self._move_visual_cursor((row, col))
            return True

        if key == "0":
            self._move_visual_cursor((row, 0))
            return True
        if key == "$":
            line = doc.get_line(row)
            self._move_visual_cursor((row, len(line)))
            return True
        if key == "^":
            line = doc.get_line(row)
            nws = 0
            while nws < len(line) and line[nws].isspace():
                nws += 1
            self._move_visual_cursor((row, nws))
            return True

        if key == "g":
            self._pending_keys = "g"
            self._pending_count = count if has_count else None
            return True
        if key == "G":
            if has_count:
                target = max(0, min(count - 1, doc.line_count - 1))
            else:
                target = doc.line_count - 1
            self._move_visual_cursor((target, 0))
            return True

        if key in "fFtT":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            return True

        if key in ";," and self._last_char_search:
            motion, target_char = self._last_char_search
            if key == ",":
                motion = motion.swapcase()
            col_offset = 0
            if motion == "t":
                col_offset = 1
            elif motion == "T":
                col_offset = -1
            self._execute_visual_char_search(
                motion, target_char, count, col_offset=col_offset
            )
            return True

        if key in "ai":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            return True

        if event.key in ("ctrl+d", "ctrl+u"):
            half = max(1, self.size.height // 2)
            target = min(row + half, doc.line_count - 1)
            if event.key == "ctrl+u":
                target = max(row - half, 0)
            self._move_visual_cursor((target, col))
            return True

        if key in ("d", "x"):
            self._apply_visual_operator("d")
            return True
        if key in ("c", "s"):
            self._apply_visual_operator("c")
            return True
        if key == "y":
            self._apply_visual_operator("y")
            return True
        if key == "p":
            self._replace_visual_selection_with_register(count)
            return True
        if key == "~":
            self._toggle_visual_case()
            return True

        return True
