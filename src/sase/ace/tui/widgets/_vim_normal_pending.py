"""Vim normal-mode pending key sequence handling for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
    find_a_paragraph_rows,
    find_a_word,
    find_a_WORD,
    find_inner_word,
    find_inner_WORD,
    find_inner_paragraph_rows,
    find_prev_word_end,
    find_prev_WORD_end,
)
from sase.ace.tui.widgets._vim_text_objects import (
    find_quote_or_bracket_text_object,
    is_quote_or_bracket_text_object_key,
)
from sase.ace.tui.widgets._vim_visual import VimVisualModeMixin


class VimNormalPendingMixin(VimVisualModeMixin):
    """Mixin for normal-mode multi-key sequence resolution."""

    if TYPE_CHECKING:

        def _dispatch_host_g_prefix_key(self, key: str) -> bool: ...

        def _search_word_under_cursor(
            self,
            *,
            reverse: bool = False,
            whole_word: bool = True,
            count: int = 1,
        ) -> bool: ...

    def _handle_normal_pending_key(self, key: str, event: Key) -> bool:
        """Handle a key after a pending normal-mode prefix."""
        pending = self._pending_keys
        self._pending_keys = ""
        pending_count = self._pending_count
        self._pending_count = None
        self._clear_count_prefix()
        doc = self.document

        # Host-specific ``g`` continuations win over vim's own ``g`` commands:
        # let the host try to dispatch ``g<enter>`` / ``gf`` / ``gG`` / ``gj`` /
        # ``gk`` / ``gJ`` / ``gK`` / ``g-`` / ``g=`` / ``gs`` first (the prompt
        # bar forwards these to its stack actions). Anything the host does not
        # own (``gg``, ``ge``/``gE``, ``gu``/``gU``/``g~``) falls through to the
        # vim branches below. The pending state is already cleared, so the
        # trailing ``_update_count_display`` hides the ``g`` hint panel either
        # way and an unknown ``gX`` never leaves the hints stuck open.
        if pending == "g":
            if self._dispatch_host_g_prefix_key(key):
                self._update_count_display()
                return True

        if pending == "surround":
            char = event.character
            if char is None and event.key == "space":
                char = " "
            if char is None:
                self._pending_surround_range = None
                self._mutation_key_buffer.clear()
            else:
                self._apply_pending_surround(char)
            self._update_count_display()
            return True

        if pending == "delete-surround":
            char = event.character
            if char is None and event.key == "space":
                char = " "
            if char is None:
                self._mutation_key_buffer.clear()
            else:
                count = pending_count if pending_count is not None else 1
                self._mutation_count = max(1, count)
                self._delete_surround(char, count)
            self._update_count_display()
            return True

        if pending == "change-surround-old":
            char = event.character
            if char is None and event.key == "space":
                char = " "
            if char is None:
                self._pending_change_surround_locations = None
                self._mutation_key_buffer.clear()
            else:
                self._mutation_count = max(
                    1,
                    pending_count if pending_count is not None else 1,
                )
                self._queue_pending_change_surround(
                    char,
                    pending_count if pending_count is not None else 1,
                )
            self._update_count_display()
            return True

        if pending == "change-surround-new":
            char = event.character
            if char is None and event.key == "space":
                char = " "
            if char is None:
                self._pending_change_surround_locations = None
                self._mutation_key_buffer.clear()
            else:
                self._change_pending_surround(char)
            self._update_count_display()
            return True

        if pending == "g" and key in "uU~":
            self._pending_operator = f"g{key}"
            self._pending_operator_count = (
                pending_count if pending_count is not None else 1
            )
            self._update_count_display()
        elif pending == "g" and key == "g":
            if pending_count is not None:
                target = max(0, min(pending_count - 1, self.document.line_count - 1))
            else:
                target = 0
            if self._pending_operator:
                op = self._pending_operator
                op_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
                cur_row = self.cursor_location[0]
                first = min(cur_row, target)
                last = max(cur_row, target)
                self._mutation_count = max(
                    1,
                    pending_count if pending_count is not None else op_count,
                )
                self._execute_linewise_operator(first, last, op)
                self._update_count_display()
            else:
                self.cursor_location = (target, 0)
        elif pending == "g" and key in "eE":
            motion_count = pending_count if pending_count is not None else 1
            op_info = self._consume_pending_operator(motion_count)
            eff = op_info[1] if op_info else motion_count
            r, c = self.cursor_location
            finder = find_prev_word_end if key == "e" else find_prev_WORD_end
            for _ in range(eff):
                nr, nc = finder(doc, r, c)
                if (nr, nc) == (r, c):
                    # Pinned at the buffer-start clamp; counting further would spin.
                    break
                r, c = nr, nc
            moved = (r, c) != self.cursor_location
            if op_info:
                # A motion that cannot move aborts the operator.
                if moved:
                    end_row, end_col = self.cursor_location
                    line = doc.get_line(end_row)
                    if end_col < len(line):
                        end_col += 1
                    self._execute_charwise_operator(
                        (r, c), (end_row, end_col), op_info[0]
                    )
            elif moved:
                self.cursor_location = (r, c)
        elif pending == "g" and key in "*#":
            motion_count = pending_count if pending_count is not None else 1
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
            self._search_word_under_cursor(
                reverse=key == "#", whole_word=False, count=motion_count
            )
        elif pending in "fFtT":
            target_char = key
            motion_count = pending_count if pending_count is not None else 1
            op_info = self._consume_pending_operator(motion_count)
            self._last_char_search = (pending, target_char)
            self._execute_char_search(pending, target_char, motion_count, op_info)
        elif pending == "r":
            if event.character is not None and len(event.character) == 1:
                self._replace_chars(
                    pending_count if pending_count is not None else 1,
                    event.character,
                )
        elif pending in {"[", "]"}:
            if event.key == "space" or event.character == " " or key in {" ", "space"}:
                count = pending_count if pending_count is not None else 1
                self._insert_blank_lines(
                    above=pending == "[",
                    count=count,
                )
            else:
                self._mutation_key_buffer.clear()
        elif pending == "a" and key == "e":
            if self._pending_operator:
                op = self._pending_operator
                op_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
                last_row = self.document.line_count - 1
                self._mutation_count = max(1, op_count)
                self._execute_linewise_operator(0, last_row, op)
                self._update_count_display()
        elif pending in "ai" and key in "wWp":
            if self._pending_operator:
                motion_count = pending_count if pending_count is not None else 1
                op = self._pending_operator
                op_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
                eff = op_count * motion_count
                self._mutation_count = max(1, eff)
                row, col = self.cursor_location
                if key == "p":
                    if pending == "i":
                        first, last = find_inner_paragraph_rows(self.document, row, eff)
                    else:
                        first, last = find_a_paragraph_rows(self.document, row, eff)
                    self._execute_linewise_operator(first, last, op)
                else:
                    is_inner = pending == "i"
                    is_WORD = key == "W"
                    if is_inner:
                        if is_WORD:
                            sr, sc, er, ec = find_inner_WORD(
                                self.document, row, col, eff
                            )
                        else:
                            sr, sc, er, ec = find_inner_word(
                                self.document, row, col, eff
                            )
                    elif is_WORD:
                        sr, sc, er, ec = find_a_WORD(self.document, row, col, eff)
                    else:
                        sr, sc, er, ec = find_a_word(self.document, row, col, eff)
                    self._execute_charwise_operator((sr, sc), (er, ec), op)
                self._update_count_display()
        elif pending in "ai" and is_quote_or_bracket_text_object_key(key):
            if self._pending_operator:
                motion_count = pending_count if pending_count is not None else 1
                op = self._pending_operator
                op_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
                eff = op_count * motion_count
                self._mutation_count = max(1, eff)
                row, col = self.cursor_location
                text_object = find_quote_or_bracket_text_object(
                    self.document,
                    row,
                    col,
                    pending,
                    key,
                    eff,
                )
                if text_object is None:
                    self._mutation_key_buffer.clear()
                else:
                    sr, sc, er, ec = text_object
                    self._execute_charwise_operator((sr, sc), (er, ec), op)
                self._update_count_display()

        self._update_count_display()
        return True
