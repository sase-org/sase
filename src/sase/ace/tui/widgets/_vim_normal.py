"""Vim normal-mode key handling mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.widgets._vim_motions import (
    find_char_backward,
    find_char_forward,
    find_next_word_end,
    find_next_word_start,
    find_next_WORD_end,
    find_next_WORD_start,
    find_prev_word_start,
    find_prev_WORD_start,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class VimNormalModeMixin(_MixinBase):
    """Mixin providing vim normal-mode key handling.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes set by PromptTextArea.__init__ (declared for type checking) --
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

    # -- Methods defined on PromptTextArea (stubs for type checking) --

    def _find_prompt_bar(self) -> Any: ...

    def _enter_insert_mode(self) -> None: ...

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

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

        # Track keys for dot-repeat
        if not self._replaying_dot:
            if (
                not self._pending_operator
                and not self._pending_keys
                and not self._count_prefix
            ):
                self._mutation_key_buffer.clear()
            self._mutation_key_buffer.append(key)

        # Handle pending key sequences (gg) ----------------------------------
        if self._pending_keys:
            pending = self._pending_keys
            self._pending_keys = ""
            pending_count = self._pending_count
            self._pending_count = None
            self._clear_count_prefix()
            if pending == "g" and key == "g":
                if pending_count is not None:
                    target = max(
                        0, min(pending_count - 1, self.document.line_count - 1)
                    )
                else:
                    target = 0
                if self._pending_operator:
                    op = self._pending_operator
                    self._pending_operator = ""
                    self._pending_operator_count = 1
                    cur_row = self.cursor_location[0]
                    first = min(cur_row, target)
                    last = max(cur_row, target)
                    self._execute_linewise_operator(first, last, op)
                    self._update_count_display()
                else:
                    self.cursor_location = (target, 0)
            elif pending in "fFtT":
                # Character search: key is the target character.
                target_char = key
                motion_count = pending_count if pending_count is not None else 1
                op_info = self._consume_pending_operator(motion_count)
                self._last_char_search = (pending, target_char)
                self._execute_char_search(pending, target_char, motion_count, op_info)
            elif pending == "a" and key == "e":
                # "ae" text object: entire buffer
                if self._pending_operator:
                    op = self._pending_operator
                    self._pending_operator = ""
                    self._pending_operator_count = 1
                    last_row = self.document.line_count - 1
                    self._execute_linewise_operator(0, last_row, op)
                    self._update_count_display()
            return True

        # Escape --------------------------------------------------------------
        if event.key == "escape":
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._clear_count_prefix()
                self._update_count_display()
                return True
            self._clear_count_prefix()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return True

        # Count prefix accumulation: 1-9 starts, 0 appends to existing
        if key in "123456789" or (key == "0" and self._count_prefix):
            self._count_prefix += key
            self._update_count_display()
            return True

        # Consume count prefix
        has_count = bool(self._count_prefix)
        count = int(self._count_prefix) if self._count_prefix else 1
        self._clear_count_prefix()

        # Dot-repeat
        if key == ".":
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._update_count_display()
            self._mutation_key_buffer.clear()
            self._replay_dot(count)
            return True

        # Operator doubling (dd, cc) -----------------------------------------
        if self._pending_operator and key == self._pending_operator:
            op = self._pending_operator
            op_count = self._pending_operator_count
            self._pending_operator = ""
            self._pending_operator_count = 1
            total = op_count * count
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + total - 1, self.document.line_count - 1)
            self._execute_linewise_operator(cur_row, last_row, op)
            self._update_count_display()
            return True

        # Start operator-pending mode (d, c) ---------------------------------
        if key in ("d", "c") and not self._pending_operator:
            self._pending_operator = key
            self._pending_operator_count = count
            self._update_count_display()
            return True

        # --- Motions (with optional operator application) --------------------

        # Basic character movement
        if key == "h":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                row, col = self.cursor_location
                target_col = max(0, col - eff)
                self._execute_charwise_operator((row, target_col), (row, col), op)
            else:
                for _ in range(count):
                    self.action_cursor_left()
            return True
        if key == "j":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                cur_row = self.cursor_location[0]
                target = min(cur_row + eff, self.document.line_count - 1)
                self._execute_linewise_operator(cur_row, target, op)
            else:
                row, col = self.cursor_location
                target = min(row + count, self.document.line_count - 1)
                self.cursor_location = (target, col)
            return True
        if key == "k":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                cur_row = self.cursor_location[0]
                target = max(cur_row - eff, 0)
                self._execute_linewise_operator(target, cur_row, op)
            else:
                row, col = self.cursor_location
                target = max(row - count, 0)
                self.cursor_location = (target, col)
            return True
        if key == "l":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                row, col = self.cursor_location
                line = self.document.get_line(row)
                target_col = min(len(line), col + eff)
                self._execute_charwise_operator((row, col), (row, target_col), op)
            else:
                for _ in range(count):
                    self.action_cursor_right()
            return True

        # Word motions
        doc = self.document
        if key == "w":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_word_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    self.cursor_location, (r, c), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "W":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_WORD_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    self.cursor_location, (r, c), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "b":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_prev_word_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    (r, c), self.cursor_location, op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "B":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_prev_WORD_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    (r, c), self.cursor_location, op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "e":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_word_end(doc, r, c)
            if op_info:
                # Inclusive: extend end past the last character
                self._execute_charwise_operator(
                    self.cursor_location, (r, c + 1), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "E":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_WORD_end(doc, r, c)
            if op_info:
                # Inclusive: extend end past the last character
                self._execute_charwise_operator(
                    self.cursor_location, (r, c + 1), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True

        # Line position motions
        if key == "0":
            op_info = self._consume_pending_operator(count)
            if op_info:
                row, col = self.cursor_location
                self._execute_charwise_operator((row, 0), (row, col), op_info[0])
            else:
                row = self.cursor_location[0]
                self.cursor_location = (row, 0)
            return True
        if key == "$":
            op_info = self._consume_pending_operator(count)
            if op_info:
                row, col = self.cursor_location
                line = doc.get_line(row)
                self._execute_charwise_operator(
                    (row, col), (row, len(line)), op_info[0]
                )
            else:
                row = self.cursor_location[0]
                line = doc.get_line(row)
                self.cursor_location = (row, len(line))
            return True
        if key == "^":
            op_info = self._consume_pending_operator(count)
            row = self.cursor_location[0]
            line = doc.get_line(row)
            nws = 0
            while nws < len(line) and line[nws].isspace():
                nws += 1
            if op_info:
                col = self.cursor_location[1]
                self._execute_charwise_operator(
                    (row, min(col, nws)), (row, max(col, nws)), op_info[0]
                )
            else:
                self.cursor_location = (row, nws)
            return True

        # Document motions
        if key == "g":
            self._pending_keys = "g"
            self._pending_count = count if has_count else None
            # Keep pending operator for gg resolution
            return True
        if key == "G":
            op_info = self._consume_pending_operator(1)
            if op_info:
                op = op_info[0]
                if has_count:
                    target = max(0, min(count - 1, self.document.line_count - 1))
                else:
                    target = self.document.line_count - 1
                cur_row = self.cursor_location[0]
                first = min(cur_row, target)
                last = max(cur_row, target)
                self._execute_linewise_operator(first, last, op)
            else:
                if has_count:
                    target = max(0, min(count - 1, self.document.line_count - 1))
                    self.cursor_location = (target, 0)
                else:
                    last_row = self.document.line_count - 1
                    self.cursor_location = (last_row, 0)
            return True

        # Character search motions (f/F/t/T)
        if key in "fFtT":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            # Keep pending operator for resolution
            return True

        # Repeat last character search (; = same direction, , = reverse)
        if key in ";," and self._last_char_search:
            motion, target_char = self._last_char_search
            if key == ",":
                motion = motion.swapcase()
            op_info = self._consume_pending_operator(count)
            # t/T leave the cursor one position away from the target,
            # so repeating would find the same character again.  Shift
            # the search start to skip past it.
            col_offset = 0
            if motion == "t":
                col_offset = 1
            elif motion == "T":
                col_offset = -1
            self._execute_char_search(
                motion, target_char, count, op_info, col_offset=col_offset
            )
            return True

        # Text object prefix (ae = entire buffer)
        if key == "a" and self._pending_operator:
            self._pending_keys = "a"
            return True

        # Cancel pending operator on unrecognized motion key
        if self._pending_operator:
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._update_count_display()
            return True

        # Half-page scroll (ctrl+d / ctrl+u)
        if event.key in ("ctrl+d", "ctrl+u"):
            half = max(1, self.size.height // 2)
            row, col = self.cursor_location
            if event.key == "ctrl+d":
                target_row = min(row + half, self.document.line_count - 1)
            else:
                target_row = max(row - half, 0)
            self.cursor_location = (target_row, col)
            return True

        # Undo
        if key == "u":
            was_readonly = self.read_only
            self.read_only = False
            self.undo()
            self.read_only = was_readonly
            return True

        # Mode switching
        if key == "i":
            self._enter_insert_mode()
            return True
        if key == "a":
            row, col = self.cursor_location
            line = self.document.get_line(row)
            self._enter_insert_mode()
            if col < len(line):
                self.cursor_location = (row, col + 1)
            return True
        if key == "A":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            return True
        if key == "I":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            col = 0
            while col < len(line) and line[col].isspace():
                col += 1
            self._enter_insert_mode()
            self.cursor_location = (row, col)
            return True
        if key == "o":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return True
        if key == "O":
            row = self.cursor_location[0]
            self._enter_insert_mode()
            self.cursor_location = (row, 0)
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            self.cursor_location = (row, 0)
            return True

        # Shortcut operators (C = c$, D = d$)
        if key in ("C", "D"):
            row, col = self.cursor_location
            line = doc.get_line(row)
            op = "c" if key == "C" else "d"
            self._execute_charwise_operator((row, col), (row, len(line)), op)
            return True

        # Join lines (J)
        if key == "J":
            self._join_lines(count)
            return True

        # Unhandled key - let it through for arrow keys, etc.
        return False
