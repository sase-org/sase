"""Vim normal-mode editing and mode-switch dispatch for PromptTextArea."""

from __future__ import annotations

from textual.events import Key

from sase.ace.tui.widgets._vim_normal_motions import VimNormalMotionsMixin


class VimNormalEditingMixin(VimNormalMotionsMixin):
    """Mixin for normal-mode edit commands and mode changes."""

    def _handle_normal_edit_key(
        self,
        key: str,
        event: Key,
        count: int,
        has_count: bool,
    ) -> bool:
        """Handle non-motion normal-mode commands."""
        doc = self.document

        if key == "u":
            was_readonly = self.read_only
            self.read_only = False
            self.undo()
            self.read_only = was_readonly
            return True
        if event.key == "ctrl+r":
            self._redo()
            return True

        if key == "v":
            self._enter_visual_mode("charwise")
            return True
        if key == "V":
            self._enter_visual_mode("linewise")
            return True
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

        if key == "Y":
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + count - 1, self.document.line_count - 1)
            self._execute_linewise_operator(cur_row, last_row, "y")
            return True

        if key in ("C", "D"):
            row, col = self.cursor_location
            line = doc.get_line(row)
            op = "c" if key == "C" else "d"
            self._execute_charwise_operator((row, col), (row, len(line)), op)
            return True
        if key == "S":
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + count - 1, self.document.line_count - 1)
            self._execute_linewise_operator(cur_row, last_row, "c")
            return True

        if key in ("p", "P"):
            self._paste_vim_register(before=key == "P", count=count)
            return True

        if key in ("x", "s"):
            row, col = self.cursor_location
            line = doc.get_line(row)
            end_col = min(col + count, len(line))
            op = "c" if key == "s" else "d"
            self._execute_charwise_operator((row, col), (row, end_col), op)
            return True
        if key == "X":
            row, col = self.cursor_location
            start_col = max(0, col - count)
            self._execute_charwise_operator((row, start_col), (row, col), "d")
            return True
        if key == "r":
            self._pending_keys = "r"
            self._pending_count = count if has_count else None
            self._update_count_display()
            return True

        if key == "~":
            self._toggle_case(count)
            return True

        if key == "J":
            self._join_lines(count)
            return True

        return False
