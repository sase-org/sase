"""Vim visual-mode pending-prefix and text-object handling for PromptTextArea."""

from __future__ import annotations

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
    find_a_paragraph_rows,
    find_a_WORD,
    find_a_word,
    find_char_backward,
    find_char_forward,
    find_inner_WORD,
    find_inner_paragraph_rows,
    find_inner_word,
)
from sase.ace.tui.widgets._vim_text_objects import (
    find_quote_or_bracket_text_object,
    is_quote_or_bracket_text_object_key,
)
from sase.ace.tui.widgets._vim_visual_ops import VimVisualOperatorMixin


class VimVisualPendingMixin(VimVisualOperatorMixin):
    """Mixin for visual-mode multi-key sequence and text-object resolution."""

    def _handle_visual_pending_key(self, key: str, event: Key) -> bool:
        """Handle a key after a visual pending prefix."""
        pending = self._pending_keys
        self._pending_keys = ""
        pending_count = self._pending_count
        self._pending_count = None
        motion_count = pending_count if pending_count is not None else 1

        if pending == "visual-surround":
            char = event.character
            if char is None and event.key == "space":
                char = " "
            if char is None or len(char) != 1 or not char.isprintable():
                self._pending_visual_surround_range = None
                self._enter_normal_mode()
            else:
                self._apply_pending_visual_surround(char)
            return True

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

        if pending in "ai" and key in "wWp":
            row, col = self._visual_cursor or self.cursor_location
            if key == "p":
                if pending == "i":
                    first, last = find_inner_paragraph_rows(
                        self.document, row, motion_count
                    )
                else:
                    first, last = find_a_paragraph_rows(
                        self.document, row, motion_count
                    )
                self._select_visual_line_range(first, last)
            else:
                is_inner = pending == "i"
                is_WORD = key == "W"
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

        if pending in "ai" and is_quote_or_bracket_text_object_key(key):
            row, col = self._visual_cursor or self.cursor_location
            text_object = find_quote_or_bracket_text_object(
                self.document,
                row,
                col,
                pending,
                key,
                motion_count,
            )
            if text_object is not None:
                sr, sc, er, ec = text_object
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


__all__ = ["VimVisualPendingMixin"]
