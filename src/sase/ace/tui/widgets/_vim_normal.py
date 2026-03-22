"""Vim normal-mode key handling mixin for PromptTextArea."""

from __future__ import annotations

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
    find_next_word_end,
    find_next_word_start,
    find_next_WORD_end,
    find_next_WORD_start,
    find_prev_word_start,
    find_prev_WORD_start,
)
from sase.ace.tui.widgets._vim_normal_ops import VimNormalOpsMixin


class VimNormalModeMixin(VimNormalOpsMixin):
    """Mixin providing vim normal-mode key handling.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

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

        # Toggle case (~)
        if key == "~":
            self._toggle_case(count)
            return True

        # Join lines (J)
        if key == "J":
            self._join_lines(count)
            return True

        # Unhandled key - let it through for arrow keys, etc.
        return False
