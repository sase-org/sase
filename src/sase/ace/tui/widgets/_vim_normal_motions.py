"""Vim normal-mode motion dispatch for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
    find_next_word_end,
    find_next_word_start,
    find_next_WORD_end,
    find_next_WORD_start,
    find_next_paragraph_boundary,
    find_prev_word_start,
    find_prev_WORD_start,
    find_prev_paragraph_boundary,
    is_blank_line,
)
from sase.ace.tui.widgets._vim_normal_pending import VimNormalPendingMixin
from sase.ace.tui.widgets._vim_text_objects import (
    find_matching_bracket,
    location_after_char,
)


class VimNormalMotionsMixin(VimNormalPendingMixin):
    """Mixin for normal-mode motions and operator motions."""

    if TYPE_CHECKING:

        def _repeat_prompt_search(
            self,
            *,
            reverse: bool = False,
            count: int = 1,
        ) -> bool: ...

        def _search_word_under_cursor(
            self,
            *,
            reverse: bool = False,
            whole_word: bool = True,
            count: int = 1,
        ) -> bool: ...

    def _handle_normal_motion_key(
        self,
        key: str,
        event: Key,
        count: int,
        has_count: bool,
    ) -> bool:
        """Handle normal-mode motion keys."""
        doc = self.document

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
        # Vim treats <Space> as a cursor-right motion.
        if key in ("l", " "):
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

        if key in ("w", "W"):
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            use_change_end = False
            if op_info and op_info[0] == "c":
                line = doc.get_line(r)
                use_change_end = c < len(line) and not line[c].isspace()
            if key == "w":
                finder = find_next_word_end if use_change_end else find_next_word_start
            else:
                finder = find_next_WORD_end if use_change_end else find_next_WORD_start
            for _ in range(eff):
                r, c = finder(doc, r, c)
            if op_info:
                if use_change_end:
                    c += 1
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
                self._execute_charwise_operator(
                    self.cursor_location, (r, c + 1), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True

        if key == "}":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            row, col = self.cursor_location
            target_row, target_col = find_next_paragraph_boundary(doc, row, eff)
            if op_info:
                if is_blank_line(doc, target_row) and target_row > row:
                    end = (target_row, 0)
                else:
                    end = (target_row, len(doc.get_line(target_row)))
                self._execute_charwise_operator((row, col), end, op_info[0])
            else:
                self.cursor_location = (target_row, target_col)
            return True
        if key == "{":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            row, col = self.cursor_location
            target_row, target_col = find_prev_paragraph_boundary(doc, row, eff)
            if op_info:
                if is_blank_line(doc, target_row) and target_row < row:
                    start = (min(target_row + 1, doc.line_count - 1), 0)
                else:
                    start = (target_row, 0)
                self._execute_charwise_operator(start, (row, col), op_info[0])
            else:
                self.cursor_location = (target_row, target_col)
            return True

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

        if key == "g":
            self._pending_keys = "g"
            self._pending_count = count if has_count else None
            self._update_count_display()
            return True
        if key == "G":
            op_info = self._consume_pending_operator(1)
            if op_info:
                op = op_info[0]
                if has_count:
                    self._mutation_count = max(1, count)
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

        if key in "fFtT":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            self._update_count_display()
            return True

        if key in ("n", "N"):
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._update_count_display()
            return self._repeat_prompt_search(reverse=key == "N", count=count)

        if key in ("*", "#"):
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._update_count_display()
            return self._search_word_under_cursor(
                reverse=key == "#", whole_word=True, count=count
            )

        if key in ";," and self._last_char_search:
            motion, target_char = self._last_char_search
            if key == ",":
                motion = motion.swapcase()
            op_info = self._consume_pending_operator(count)
            col_offset = 0
            if motion == "t":
                col_offset = 1
            elif motion == "T":
                col_offset = -1
            self._execute_char_search(
                motion, target_char, count, op_info, col_offset=col_offset
            )
            return True

        if key == "," and not self._pending_operator:
            # The prompt-stack comma leader migrated to the ``g`` prefix
            # (``gs``/``g=`` and friends). With no reverse
            # char-search pending (handled just above), swallow ``,`` as a
            # prompt-local no-op so it never bubbles to the app-level comma
            # leader while the prompt body owns focus.
            return True

        if key == "%":
            op_info = self._consume_pending_operator(count)
            match_info = find_matching_bracket(doc, *self.cursor_location)
            if match_info is None:
                return True
            _bracket_location, match_location = match_info
            if op_info:
                op = op_info[0]
                cursor = self.cursor_location
                if cursor <= match_location:
                    self._execute_charwise_operator(
                        cursor,
                        location_after_char(doc, match_location),
                        op,
                    )
                else:
                    self._execute_charwise_operator(
                        match_location,
                        location_after_char(doc, cursor),
                        op,
                    )
            else:
                self.cursor_location = match_location
            return True

        if key in "ai" and self._pending_operator:
            self._pending_keys = key
            self._pending_count = count if has_count else None
            self._update_count_display()
            return True

        if self._pending_operator:
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._update_count_display()
            return True

        if event.key in ("ctrl+d", "ctrl+u"):
            half = max(1, self.size.height // 2)
            row, col = self.cursor_location
            if event.key == "ctrl+d":
                target_row = min(row + half, self.document.line_count - 1)
            else:
                target_row = max(row - half, 0)
            self.cursor_location = (target_row, col)
            return True

        return False
