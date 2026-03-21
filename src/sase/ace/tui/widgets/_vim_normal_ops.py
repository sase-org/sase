"""Vim normal-mode operator execution and state management helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.widgets._vim_motions import (
    find_char_backward,
    find_char_forward,
)

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
        _mutation_key_buffer: list[str]
        _last_mutation_keys: list[str]
        _replaying_dot: bool
        _last_char_search: tuple[str, str] | None

        def _find_prompt_bar(self) -> Any: ...

        def _enter_insert_mode(self) -> None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _handle_normal_mode_key(self, event: Key) -> bool: ...

    # -- Mixin implementation --

    def _update_count_display(self) -> None:
        """Update border subtitle to show the pending count/operator."""
        bar = self._find_prompt_bar()
        if bar:
            indicator = ""
            if self._pending_operator:
                if self._pending_operator_count > 1:
                    indicator += str(self._pending_operator_count)
                indicator += self._pending_operator
            if self._count_prefix:
                indicator += self._count_prefix
            if indicator:
                bar.border_subtitle = f"[Esc] cancel  [i] insert  {indicator}"
            else:
                bar.border_subtitle = "[Esc] cancel  [i] insert"

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

    def _execute_charwise_operator(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        op: str,
    ) -> None:
        """Execute a charwise ``d``/``c`` operator over *start*..*end*."""
        self._record_mutation()
        if start > end:
            start, end = end, start
        if start == end:
            if op == "c":
                self._enter_insert_mode()
            return
        deleted = self._get_text_in_range(start, end)
        if deleted:
            copy_to_system_clipboard(deleted)
        was_readonly = self.read_only
        self.read_only = False
        self.delete(start, end)
        if op == "c":
            self._enter_insert_mode()
        else:
            self.read_only = was_readonly
        self.cursor_location = start

    def _execute_linewise_operator(
        self,
        first_row: int,
        last_row: int,
        op: str,
    ) -> None:
        """Execute a linewise ``d``/``c`` operator on rows *first_row* .. *last_row*."""
        self._record_mutation()
        doc = self.document
        first_row = max(0, first_row)
        last_row = min(last_row, doc.line_count - 1)

        lines = [doc.get_line(row) for row in range(first_row, last_row + 1)]
        if lines:
            copy_to_system_clipboard("\n".join(lines))

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
