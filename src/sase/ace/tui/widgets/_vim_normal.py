"""Vim normal-mode key handling mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
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

    def _execute_charwise_operator(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        op: str,
    ) -> None:
        """Execute a charwise ``d``/``c`` operator over *start*..*end*."""
        if start > end:
            start, end = end, start
        if start == end:
            if op == "c":
                self._enter_insert_mode()
            return
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
        doc = self.document
        first_row = max(0, first_row)
        last_row = min(last_row, doc.line_count - 1)

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

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

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
                for _ in range(count):
                    self.action_cursor_down()
            return True
        if key == "k":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                cur_row = self.cursor_location[0]
                target = max(cur_row - eff, 0)
                self._execute_linewise_operator(target, cur_row, op)
            else:
                for _ in range(count):
                    self.action_cursor_up()
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

        # Cancel pending operator on unrecognized motion key
        if self._pending_operator:
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._update_count_display()
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

        # Unhandled key - let it through for arrow keys, etc.
        return False
