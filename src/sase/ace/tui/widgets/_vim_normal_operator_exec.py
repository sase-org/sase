"""Vim normal-mode operator execution helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.widgets._vim_motions import (
    find_char_backward,
    find_char_forward,
)
from sase.ace.tui.widgets._vim_number import compute_number_change
from sase.ace.tui.widgets._vim_normal_surround import VimNormalSurroundMixin
from sase.ace.tui.widgets._vim_registers import first_non_blank_col
from sase.ace.tui.widgets._vim_transforms import (
    apply_case_operator,
    apply_indent_operator,
)


class VimNormalOperatorExecutionMixin(VimNormalSurroundMixin):
    """Mixin providing vim normal-mode operator execution helpers."""

    if TYPE_CHECKING:

        def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None: ...
        def _flash_yank(
            self,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...
        def _normal_join_next_line_text(self, next_line: str) -> str: ...

    def _execute_charwise_operator(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        op: str,
    ) -> None:
        """Execute a charwise vim operator over *start*..*end*."""
        if start > end:
            start, end = end, start
        if op == "ys":
            self._queue_pending_surround_range("charwise", start, end)
            return
        if self._is_indent_operator(op):
            self._execute_linewise_transform_operator(start[0], end[0], op)
            return
        if self._is_case_operator(op):
            self._execute_charwise_case_operator(start, end, op)
            return
        if start == end:
            if op == "c":
                self._record_mutation()
                self._enter_insert_mode()
                self._start_dot_insert_capture()
            else:
                # An empty delete performs no edit; recording it would
                # overwrite the dot-repeat register with a no-op.
                self._mutation_key_buffer.clear()
            return
        text = self._get_text_in_range(start, end)
        if op == "y":
            self._store_vim_register(text, "charwise")
            if text:
                schedule_copy_delivery(
                    self,
                    text,
                    copied_label="yanked text",
                    task_name="sase-copy-vim-charwise-yank",
                    on_failure="toast",
                )
                self._flash_yank(start, end)
            self.cursor_location = start
            self._mutation_key_buffer.clear()
            return
        self._record_mutation()
        self._store_vim_register(text, "charwise")
        if text:
            schedule_copy_delivery(
                self,
                text,
                copied_label="deleted text",
                task_name="sase-copy-vim-charwise-delete",
                on_failure="toast",
            )
        was_readonly = self.read_only
        self.read_only = False
        self.delete(start, end)
        if op == "c":
            self.cursor_location = start
            self._enter_insert_mode()
            self._start_dot_insert_capture()
        else:
            self.read_only = was_readonly
            self.cursor_location = start

    def _execute_charwise_case_operator(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        op: str,
    ) -> None:
        """Execute a charwise case operator over *start*..*end*."""
        if start >= end:
            self._mutation_key_buffer.clear()
            return

        text = self._get_text_in_range(start, end)
        replacement = apply_case_operator(text, op)
        self._record_mutation()
        if replacement != text:
            was_readonly = self.read_only
            self.read_only = False
            self._replace_via_keyboard(replacement, start, end)
            self.read_only = was_readonly
        self.cursor_location = start

    def _replace_chars(self, count: int, replacement: str) -> None:
        """Replace *count* characters at the cursor with *replacement*."""
        if len(replacement) != 1:
            return
        row, col = self.cursor_location
        line = self.document.get_line(row)
        end_col = col + count
        if col >= len(line) or end_col > len(line):
            return

        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(replacement * count, (row, col), (row, end_col))
        self.read_only = was_readonly
        self.cursor_location = (row, end_col - 1)
        self._mutation_count = max(1, count)
        self._record_mutation()

    def _redo(self) -> None:
        """Redo the most recently undone TextArea edit."""
        was_readonly = self.read_only
        self.read_only = False
        self.redo()
        self.read_only = was_readonly
        self._clear_prompt_search(clear_highlights=True)

    def _execute_linewise_operator(
        self,
        first_row: int,
        last_row: int,
        op: str,
    ) -> None:
        """Execute a linewise operator on rows *first_row* .. *last_row*."""
        if op == "ys":
            doc = self.document
            first_row = max(0, min(first_row, doc.line_count - 1))
            last_row = max(0, min(last_row, doc.line_count - 1))
            if first_row > last_row:
                first_row, last_row = last_row, first_row
            self._queue_pending_surround_range(
                "linewise",
                (first_row, 0),
                (last_row, len(doc.get_line(last_row))),
            )
            return
        if self._is_indent_operator(op) or self._is_case_operator(op):
            self._execute_linewise_transform_operator(first_row, last_row, op)
            return

        doc = self.document
        first_row = max(0, first_row)
        last_row = min(last_row, doc.line_count - 1)

        lines = [doc.get_line(row) for row in range(first_row, last_row + 1)]
        text = "\n".join(lines)
        self._store_vim_register(text, "linewise")
        if op == "y":
            if lines:
                schedule_copy_delivery(
                    self,
                    text,
                    copied_label="yanked lines",
                    task_name="sase-copy-vim-linewise-yank",
                    on_failure="toast",
                )
            if text:
                self._flash_yank(
                    (first_row, 0),
                    (last_row, len(lines[-1])),
                )
            self._mutation_key_buffer.clear()
            return

        self._record_mutation()
        if lines:
            schedule_copy_delivery(
                self,
                text,
                copied_label="deleted lines",
                task_name="sase-copy-vim-linewise-delete",
                on_failure="toast",
            )

        was_readonly = self.read_only
        self.read_only = False

        if op == "c":
            # Change: clear line contents but keep one empty line.
            last_line = doc.get_line(last_row)
            self.delete((first_row, 0), (last_row, len(last_line)))
            self.cursor_location = (first_row, 0)
            self._enter_insert_mode()
            self._start_dot_insert_capture()
        else:
            # Delete: remove lines entirely.
            if first_row == 0 and last_row >= doc.line_count - 1:
                last_line = doc.get_line(last_row)
                self.delete((0, 0), (last_row, len(last_line)))
                self.cursor_location = (0, 0)
            elif last_row >= doc.line_count - 1:
                prev_line = doc.get_line(first_row - 1)
                last_line = doc.get_line(last_row)
                self.delete(
                    (first_row - 1, len(prev_line)),
                    (last_row, len(last_line)),
                )
                self.cursor_location = (first_row - 1, 0)
            else:
                self.delete((first_row, 0), (last_row + 1, 0))
                self.cursor_location = (first_row, 0)
            self.read_only = was_readonly

    def _execute_linewise_transform_operator(
        self,
        first_row: int,
        last_row: int,
        op: str,
        *,
        units: int = 1,
    ) -> None:
        """Execute a line-preserving transform on rows *first_row*..*last_row*."""
        doc = self.document
        first_row = max(0, min(first_row, doc.line_count - 1))
        last_row = max(0, min(last_row, doc.line_count - 1))
        if first_row > last_row:
            first_row, last_row = last_row, first_row

        lines = [doc.get_line(row) for row in range(first_row, last_row + 1)]
        if self._is_indent_operator(op):
            transformed = apply_indent_operator(lines, op, units=units)
        else:
            transformed = [apply_case_operator(line, op) for line in lines]

        original = "\n".join(lines)
        replacement = "\n".join(transformed)
        self._record_mutation()
        if replacement != original:
            was_readonly = self.read_only
            self.read_only = False
            self._replace_via_keyboard(
                replacement,
                (first_row, 0),
                (last_row, len(doc.get_line(last_row))),
            )
            self.read_only = was_readonly

        first_line = transformed[0] if transformed else ""
        self.cursor_location = (first_row, first_non_blank_col(first_line))

    def _last_char_location_after_insert(
        self,
        start: tuple[int, int],
        text: str,
    ) -> tuple[int, int]:
        """Return the location of the last inserted character for charwise paste."""
        row, col = start
        if not text:
            return start
        lines = text.split("\n")
        if len(lines) == 1:
            return (row, col + len(text) - 1)
        last_line = lines[-1]
        last_row = row + len(lines) - 1
        if last_line:
            return (last_row, len(last_line) - 1)
        return (last_row, 0)

    def _paste_vim_register(self, *, before: bool, count: int) -> None:
        """Paste the internal unnamed Vim register."""
        register = self._vim_register
        count = max(1, count)
        if register.kind == "charwise":
            self._paste_charwise_register(register.text, before=before, count=count)
        else:
            self._paste_linewise_register(register.text, before=before, count=count)

    def _paste_charwise_register(
        self,
        text: str,
        *,
        before: bool,
        count: int,
    ) -> None:
        """Paste charwise register text before or after the cursor."""
        insert_text = text * count
        if not insert_text:
            self._mutation_key_buffer.clear()
            return

        row, col = self.cursor_location
        line = self.document.get_line(row)
        if before or col >= len(line):
            insert_at = (row, col)
        else:
            insert_at = (row, col + 1)

        self._record_mutation()
        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(insert_text, insert_at, insert_at)
        self.read_only = was_readonly
        self.cursor_location = self._last_char_location_after_insert(
            insert_at, insert_text
        )

    def _paste_linewise_register(
        self,
        text: str,
        *,
        before: bool,
        count: int,
    ) -> None:
        """Paste linewise register text above or below the cursor."""
        register_lines = text.split("\n") * count
        insert_text = "\n".join(register_lines)
        doc = self.document
        row = self.cursor_location[0]

        if doc.line_count == 1 and doc.get_line(0) == "":
            insert_at = (0, 0)
            start_row = 0
            payload = insert_text
        elif before:
            insert_at = (row, 0)
            start_row = row
            payload = insert_text + "\n"
        elif row >= doc.line_count - 1:
            line = doc.get_line(row)
            insert_at = (row, len(line))
            start_row = row + 1
            payload = "\n" + insert_text
        else:
            insert_at = (row + 1, 0)
            start_row = row + 1
            payload = insert_text + "\n"

        self._record_mutation()
        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(payload, insert_at, insert_at)
        self.read_only = was_readonly
        self.cursor_location = (
            start_row,
            first_non_blank_col(register_lines[0] if register_lines else ""),
        )

    def _toggle_case(self, count: int) -> None:
        """Toggle case of *count* characters at cursor (vim ``~``).

        Swaps upper<->lower for each character, then advances the cursor.
        Non-alpha characters are skipped over without modification.
        """
        row, col = self.cursor_location
        line = self.document.get_line(row)
        if col >= len(line):
            return
        end = min(col + count, len(line))
        segment = line[col:end]
        toggled = segment.swapcase()
        if toggled == segment:
            # Nothing changed - just advance cursor.
            self.cursor_location = (row, end)
            return
        was_readonly = self.read_only
        self.read_only = False
        self.delete((row, col), (row, end))
        self._replace_via_keyboard(toggled, (row, col), (row, col))
        self.read_only = was_readonly
        self.cursor_location = (row, end)
        self._record_mutation()

    def _apply_number_change(self, delta: int) -> None:
        """Increment or decrement the next number in the prompt by *delta*."""
        cursor = self._absolute_offset(self.cursor_location)
        change = compute_number_change(self.text, cursor, delta)
        if change is None:
            return

        start = self._location_from_absolute(change.start)
        end = self._location_from_absolute(change.end)
        was_readonly = self.read_only
        self.read_only = False
        self.delete(start, end)
        self._replace_via_keyboard(change.new_text, start, start)
        self.read_only = was_readonly
        self.cursor_location = self._location_from_absolute(change.new_cursor)
        self._record_mutation()

    def _join_lines(self, count: int) -> None:
        """Join the current line with the next *count* lines (vim ``J``).

        Replaces each newline with a single space.  Trailing whitespace on the
        current line and leading whitespace on the joined line are collapsed.
        The cursor is placed at the join point.
        """
        doc = self.document
        row = self.cursor_location[0]
        joins = max(1, count - 1) if count > 1 else 1

        was_readonly = self.read_only
        self.read_only = False

        join_col = 0
        for _ in range(joins):
            if row >= doc.line_count - 1:
                break
            cur_line = doc.get_line(row)
            next_line = doc.get_line(row + 1)
            # Strip trailing space on current, leading space on next.
            stripped_cur = cur_line.rstrip()
            # A fold into real content drops the pulled-up line's structural
            # prefix; pulling a line onto a blank one folds nothing, so it
            # stays verbatim.
            folded_next = (
                self._normal_join_next_line_text(next_line)
                if stripped_cur
                else next_line
            )
            stripped_next = folded_next.lstrip()
            if stripped_cur and stripped_next:
                joined = stripped_cur + " " + stripped_next
                join_col = len(stripped_cur)
            elif stripped_cur:
                joined = stripped_cur
                join_col = len(stripped_cur)
            else:
                joined = stripped_next
                join_col = 0
            self.delete((row, 0), (row + 1, len(next_line)))
            self._replace_via_keyboard(joined, (row, 0), (row, 0))

        self.cursor_location = (row, join_col)
        self.read_only = was_readonly
        self._record_mutation()

    def _insert_blank_lines(self, *, above: bool, count: int) -> None:
        """Insert blank lines above or below the current line."""
        count = max(1, count)
        row, col = self.cursor_location
        line = self.document.get_line(row)
        insert_at = (row, 0) if above else (row, len(line))

        was_readonly = self.read_only
        self.read_only = False
        try:
            self._replace_via_keyboard("\n" * count, insert_at, insert_at)
        finally:
            self.read_only = was_readonly

        self.cursor_location = (row + count, col) if above else (row, col)
        self._mutation_count = count
        self._record_mutation()

    def _execute_char_search(
        self,
        motion: str,
        target_char: str,
        count: int,
        op_info: tuple[str, int] | None,
        *,
        col_offset: int = 0,
    ) -> bool:
        """Execute a character search motion (f/F/t/T).

        *col_offset* shifts the search start column without changing the
        operator anchor.  This is used by ``;``/``,`` to avoid the "stuck
        cursor" problem when repeating ``t``/``T`` motions.

        Returns ``True`` if the character was found and the motion executed.
        """
        eff = op_info[1] if op_info else count
        row, col = self.cursor_location
        search_col = col + col_offset
        line = self.document.get_line(row)
        if motion in "ft":
            tc = find_char_forward(line, search_col, target_char, eff)
        else:
            tc = find_char_backward(line, search_col, target_char, eff)
        if tc is None:
            return False
        if motion == "f":
            if op_info:
                self._execute_charwise_operator((row, col), (row, tc + 1), op_info[0])
            else:
                self.cursor_location = (row, tc)
        elif motion == "t":
            if op_info:
                self._execute_charwise_operator((row, col), (row, tc), op_info[0])
            else:
                self.cursor_location = (row, tc - 1)
        elif motion == "F":
            if op_info:
                self._execute_charwise_operator((row, tc), (row, col + 1), op_info[0])
            else:
                self.cursor_location = (row, tc)
        elif motion == "T":
            if op_info:
                self._execute_charwise_operator(
                    (row, tc + 1), (row, col + 1), op_info[0]
                )
            else:
                self.cursor_location = (row, tc + 1)
        return True
