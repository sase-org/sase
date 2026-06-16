"""Vim normal-mode operator execution and state management helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.widgets._vim_motions import (
    find_char_backward,
    find_char_forward,
)
from sase.ace.tui.widgets._vim_registers import (
    VimRegister,
    VimRegisterKind,
    first_non_blank_col,
)
from sase.ace.tui.widgets._vim_text_objects import (
    find_quote_or_bracket_text_object,
    is_quote_or_bracket_text_object_key,
    location_after_char,
)
from sase.ace.tui.widgets._vim_transforms import (
    apply_case_operator,
    apply_indent_operator,
)

_SURROUND_PAIRS = {
    '"': ('"', '"'),
    "'": ("'", "'"),
    "`": ("`", "`"),
    "(": ("(", ")"),
    ")": ("(", ")"),
    "[": ("[", "]"),
    "]": ("[", "]"),
    "b": ("(", ")"),
    "{": ("{", "}"),
    "}": ("{", "}"),
    "B": ("{", "}"),
    "<": ("<", ">"),
    ">": ("<", ">"),
}

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class VimNormalOpsMixin(_MixinBase):
    """Mixin providing vim normal-mode operator execution and state helpers.

    Mixed into :class:`VimNormalModeMixin` which is then mixed into
    :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _vim_mode: str
        _pending_keys: str
        _count_prefix: str
        _pending_count: int | None
        _pending_operator: str
        _pending_operator_count: int
        _pending_surround_range: tuple[str, tuple[int, int], tuple[int, int]] | None
        _mutation_key_buffer: list[str]
        _last_mutation_keys: list[str]
        _replaying_dot: bool
        _last_char_search: tuple[str, str] | None
        _vim_register: VimRegister

        def _find_prompt_bar(self) -> Any: ...

        def _enter_insert_mode(self) -> None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _handle_normal_mode_key(self, event: Key) -> bool: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...

    # -- Mixin implementation --

    def _is_case_operator(self, op: str) -> bool:
        """Return whether *op* is a vim case operator."""
        return op in {"gu", "gU", "g~"}

    def _is_indent_operator(self, op: str) -> bool:
        """Return whether *op* is a vim indent/dedent operator."""
        return op in {">", "<"}

    def _is_line_repeat_key(self, op: str, key: str) -> bool:
        """Return whether *key* completes an operator's linewise form."""
        if op == "ys":
            return key == "s"
        if op in {"d", "c", "y", ">", "<"}:
            return key == op
        return (op, key) in {("gu", "u"), ("gU", "U"), ("g~", "~")}

    def _update_count_display(self) -> None:
        """Update border subtitle to show the pending count/operator."""
        bar = self._find_prompt_bar()
        if bar:
            indicator = ""
            if self._pending_operator:
                if self._pending_operator_count > 1:
                    indicator += str(self._pending_operator_count)
                indicator += self._pending_operator
            if self._pending_keys:
                if self._pending_count is not None:
                    indicator += str(self._pending_count)
                if self._pending_keys == "surround":
                    indicator += "ys"
                elif self._pending_keys == "delete-surround":
                    indicator += "ds"
                else:
                    indicator += self._pending_keys
            if self._count_prefix:
                indicator += self._count_prefix
            # Derive the base from the bar so a stacked prompt keeps advertising
            # its ,j/,k/,J/,K/- keymaps while a count/operator/comma leader is
            # pending, instead of flipping back to the single-pane hints.
            base = "[Esc] clear  [i] insert  [^C] cancel"
            getter = getattr(bar, "normal_mode_subtitle", None)
            if callable(getter):
                base = getter()
            subtitle = f"{base}  {indicator}" if indicator else base
            setter = getattr(bar, "set_prompt_mode_subtitle", None)
            if callable(setter):
                setter(subtitle)
            else:
                bar.border_subtitle = subtitle

    def _clear_count_prefix(self) -> None:
        """Clear count prefix and update display if needed."""
        if self._count_prefix:
            self._count_prefix = ""
            self._update_count_display()

    def _record_mutation(self) -> None:
        """Record the current key buffer as the last mutation for dot-repeat."""
        if not self._replaying_dot and self._mutation_key_buffer:
            self._last_mutation_keys = list(self._mutation_key_buffer)
        self._mutation_key_buffer.clear()

    def _replay_dot(self, count: int) -> None:
        """Replay the last recorded mutation *count* times."""
        if not self._last_mutation_keys:
            return
        keys = list(self._last_mutation_keys)
        self._replaying_dot = True
        try:
            for _ in range(count):
                for char in keys:
                    self._handle_normal_mode_key(Key(char, char))
        finally:
            self._replaying_dot = False

    def _consume_pending_operator(self, count: int) -> tuple[str, int] | None:
        """Consume pending operator state if present.

        Returns ``(operator, effective_count)`` where *effective_count* is the
        product of the operator's stored count and the given motion *count*, or
        ``None`` when no operator is pending.
        """
        if not self._pending_operator:
            return None
        op = self._pending_operator
        op_count = self._pending_operator_count
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._update_count_display()
        return (op, op_count * count)

    def _get_text_in_range(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> str:
        """Extract text between two ``(row, col)`` positions."""
        doc = self.document
        if start[0] == end[0]:
            return doc.get_line(start[0])[start[1] : end[1]]
        parts = [doc.get_line(start[0])[start[1] :]]
        for row in range(start[0] + 1, end[0]):
            parts.append(doc.get_line(row))
        parts.append(doc.get_line(end[0])[: end[1]])
        return "\n".join(parts)

    def _store_vim_register(self, text: str, kind: VimRegisterKind) -> None:
        """Store text in the internal unnamed Vim register."""
        self._vim_register = VimRegister(text=text, kind=kind)

    def _surround_delimiters(self, key: str) -> tuple[str, str] | None:
        """Return opening/closing delimiters for a vim-surround key."""
        if len(key) != 1:
            return None
        return _SURROUND_PAIRS.get(key, (key, key))

    def _queue_pending_surround_range(
        self,
        kind: str,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        """Remember a resolved ``ys`` target while waiting for a delimiter."""
        if start > end:
            start, end = end, start
        if kind == "charwise" and start == end:
            self._mutation_key_buffer.clear()
            return
        self._pending_surround_range = (kind, start, end)
        self._pending_keys = "surround"
        self._update_count_display()

    def _apply_pending_surround(self, key: str) -> None:
        """Wrap the pending ``ys`` target with the delimiter from *key*."""
        target = self._pending_surround_range
        self._pending_surround_range = None
        delimiters = self._surround_delimiters(key)
        if target is None or delimiters is None:
            self._mutation_key_buffer.clear()
            return

        kind, start, end = target
        if start > end:
            start, end = end, start
        text = self._get_text_in_range(start, end)
        if not text:
            self._mutation_key_buffer.clear()
            return

        open_delim, close_delim = delimiters
        if kind == "charwise":
            leading_len = len(text) - len(text.lstrip())
            without_leading = text[leading_len:]
            trailing_len = len(without_leading) - len(without_leading.rstrip())
            core_end = len(without_leading) - trailing_len
            leading = text[:leading_len]
            core = without_leading[:core_end]
            trailing = without_leading[core_end:]
            if not core:
                leading = ""
                core = text
                trailing = ""
            replacement = f"{leading}{open_delim}{core}{close_delim}{trailing}"
            cursor_offset = self._absolute_offset(start) + len(leading)
        else:
            replacement = f"{open_delim}{text}{close_delim}"
            cursor_offset = self._absolute_offset(start)

        self._record_mutation()
        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(replacement, start, end)
        self.read_only = was_readonly
        self.cursor_location = self._location_from_absolute(cursor_offset)

    def _delete_surround(self, key: str, count: int = 1) -> None:
        """Delete the nearest surrounding delimiters matching *key*."""
        locations = self._surround_locations(key, count)
        if locations is None:
            self._mutation_key_buffer.clear()
            return

        open_loc, inner_start, close_loc, outer_end = locations
        inner_text = self._get_text_in_range(inner_start, close_loc)
        self._record_mutation()
        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(inner_text, open_loc, outer_end)
        self.read_only = was_readonly
        self.cursor_location = open_loc

    def _surround_locations(
        self,
        key: str,
        count: int = 1,
    ) -> (
        tuple[
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
        ]
        | None
    ):
        """Return outer and inner locations for the surround matching *key*."""
        delimiters = self._surround_delimiters(key)
        if delimiters is None:
            return None

        open_delim, close_delim = delimiters
        if open_delim == close_delim:
            return self._same_char_surround_locations(open_delim)
        return self._paired_surround_locations(key, open_delim, close_delim, count)

    def _same_char_surround_locations(
        self,
        delimiter: str,
    ) -> (
        tuple[
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
        ]
        | None
    ):
        """Find a same-character delimiter pair enclosing the cursor."""
        row, col = self.cursor_location
        line = self.document.get_line(row)
        positions = [
            index
            for index, char in enumerate(line)
            if char == delimiter and not self._is_escaped_delimiter(line, index)
        ]
        pairs = [
            (positions[index], positions[index + 1])
            for index in range(0, len(positions) - 1, 2)
        ]
        for open_col, close_col in pairs:
            if open_col <= col <= close_col:
                open_loc = (row, open_col)
                inner_start = (row, open_col + 1)
                close_loc = (row, close_col)
                outer_end = (row, close_col + 1)
                return (open_loc, inner_start, close_loc, outer_end)
        return None

    def _paired_surround_locations(
        self,
        key: str,
        open_delim: str,
        close_delim: str,
        count: int,
    ) -> (
        tuple[
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
            tuple[int, int],
        ]
        | None
    ):
        """Find a bracket-like delimiter pair enclosing the cursor."""
        text_object_key = (
            key if is_quote_or_bracket_text_object_key(key) else open_delim
        )
        row, col = self.cursor_location
        text_object = find_quote_or_bracket_text_object(
            self.document,
            row,
            col,
            "i",
            text_object_key,
            max(1, count),
        )
        if text_object is None:
            return None

        sr, sc, er, ec = text_object
        if sc <= 0:
            return None
        open_loc = (sr, sc - 1)
        close_loc = (er, ec)
        if not self._location_has_char(open_loc, open_delim):
            return None
        if not self._location_has_char(close_loc, close_delim):
            return None
        return (
            open_loc,
            (sr, sc),
            close_loc,
            location_after_char(self.document, close_loc),
        )

    def _location_has_char(self, location: tuple[int, int], char: str) -> bool:
        """Return whether *location* points at *char* in the document."""
        row, col = location
        if row < 0 or row >= self.document.line_count:
            return False
        line = self.document.get_line(row)
        return 0 <= col < len(line) and line[col] == char

    def _is_escaped_delimiter(self, line: str, index: int) -> bool:
        """Return whether a same-character delimiter is backslash-escaped."""
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        return backslashes % 2 == 1

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
            else:
                # An empty delete performs no edit; recording it would
                # overwrite the dot-repeat register with a no-op.
                self._mutation_key_buffer.clear()
            return
        text = self._get_text_in_range(start, end)
        if op == "y":
            self._store_vim_register(text, "charwise")
            if text:
                copy_to_system_clipboard(text)
            self.cursor_location = start
            self._mutation_key_buffer.clear()
            return
        self._record_mutation()
        self._store_vim_register(text, "charwise")
        if text:
            copy_to_system_clipboard(text)
        was_readonly = self.read_only
        self.read_only = False
        self.delete(start, end)
        if op == "c":
            self._enter_insert_mode()
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
        self._record_mutation()

    def _redo(self) -> None:
        """Redo the most recently undone TextArea edit."""
        was_readonly = self.read_only
        self.read_only = False
        self.redo()
        self.read_only = was_readonly

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
                copy_to_system_clipboard(text)
            self._mutation_key_buffer.clear()
            return

        self._record_mutation()
        if lines:
            copy_to_system_clipboard(text)

        was_readonly = self.read_only
        self.read_only = False

        if op == "c":
            # Change: clear line contents but keep one empty line.
            last_line = doc.get_line(last_row)
            self.delete((first_row, 0), (last_row, len(last_line)))
            self._enter_insert_mode()
            self.cursor_location = (first_row, 0)
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

        Swaps upper↔lower for each character, then advances the cursor.
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
            # Nothing changed – just advance cursor
            self.cursor_location = (row, end)
            return
        was_readonly = self.read_only
        self.read_only = False
        self.delete((row, col), (row, end))
        self._replace_via_keyboard(toggled, (row, col), (row, col))
        self.read_only = was_readonly
        self.cursor_location = (row, end)
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
            # Strip trailing space on current, leading space on next
            stripped_cur = cur_line.rstrip()
            stripped_next = next_line.lstrip()
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
