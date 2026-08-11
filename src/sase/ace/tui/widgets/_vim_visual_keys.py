"""Vim visual-mode top-level key dispatch for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._vim_motions import (
    find_next_WORD_end,
    find_next_WORD_start,
    find_next_paragraph_boundary,
    find_next_word_end,
    find_next_word_start,
    find_prev_WORD_start,
    find_prev_paragraph_boundary,
    find_prev_word_start,
)
from sase.ace.tui.widgets._vim_text_objects import find_matching_bracket
from sase.ace.tui.widgets._vim_visual_pending import VimVisualPendingMixin


class VimVisualKeyHandlingMixin(VimVisualPendingMixin):
    """Mixin providing the top-level visual-mode key dispatcher."""

    if TYPE_CHECKING:

        def _search_visual_selection(
            self, *, reverse: bool = False, count: int = 1
        ) -> bool: ...

    def _visual_count(self) -> tuple[bool, int]:
        """Consume and return the current count prefix."""
        has_count = bool(self._count_prefix)
        count = int(self._count_prefix) if self._count_prefix else 1
        self._count_prefix = ""
        self._update_visual_display()
        return (has_count, count)

    def _handle_visual_mode_key(self, event: Key) -> bool:
        """Handle a key event in VISUAL or V-LINE mode.

        Marks *event* so a base ``VimTextArea._on_key`` reached later in
        Textual's MRO handler walk does not re-dispatch it (see that method).
        """
        event._vim_tower_dispatched = True  # type: ignore[attr-defined]
        key = event.character or event.key

        if event.key == "escape":
            self._pending_keys = ""
            self._pending_count = None
            self._pending_visual_surround_range = None
            self._count_prefix = ""
            self._enter_normal_mode()
            return True

        if self._pending_keys:
            return self._handle_visual_pending_key(key, event)

        if key in "123456789" or (key == "0" and self._count_prefix):
            self._count_prefix += key
            self._update_visual_display()
            return True

        has_count, count = self._visual_count()
        row, col = self._visual_cursor or self.cursor_location
        doc = self.document

        if key == "v":
            if self._visual_kind() == "charwise":
                self._enter_normal_mode()
            else:
                self._switch_visual_kind("charwise")
            return True
        if key == "V":
            if self._visual_kind() == "linewise":
                self._enter_normal_mode()
            else:
                self._switch_visual_kind("linewise")
            return True
        if key == "o":
            self._swap_visual_ends()
            return True

        if key == "h":
            self._move_visual_cursor((row, max(0, col - count)))
            return True
        # Vim treats <Space> as a cursor-right motion.
        if key in ("l", " "):
            line = doc.get_line(row)
            self._move_visual_cursor((row, min(len(line), col + count)))
            return True
        if key == "j":
            target = min(row + count, doc.line_count - 1)
            self._move_visual_cursor((target, col))
            return True
        if key == "k":
            target = max(row - count, 0)
            self._move_visual_cursor((target, col))
            return True

        if key == "w":
            for _ in range(count):
                row, col = find_next_word_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "W":
            for _ in range(count):
                row, col = find_next_WORD_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "b":
            for _ in range(count):
                row, col = find_prev_word_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "B":
            for _ in range(count):
                row, col = find_prev_WORD_start(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "e":
            for _ in range(count):
                row, col = find_next_word_end(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "E":
            for _ in range(count):
                row, col = find_next_WORD_end(doc, row, col)
            self._move_visual_cursor((row, col))
            return True
        if key == "}":
            row, col = find_next_paragraph_boundary(doc, row, count)
            self._move_visual_cursor((row, col))
            return True
        if key == "{":
            row, col = find_prev_paragraph_boundary(doc, row, count)
            self._move_visual_cursor((row, col))
            return True

        if key == "0":
            self._move_visual_cursor((row, 0))
            return True
        if key == "$":
            line = doc.get_line(row)
            self._move_visual_cursor((row, len(line)))
            return True
        if key == "^":
            line = doc.get_line(row)
            nws = 0
            while nws < len(line) and line[nws].isspace():
                nws += 1
            self._move_visual_cursor((row, nws))
            return True

        if key == "g":
            self._pending_keys = "g"
            self._pending_count = count if has_count else None
            return True
        if key == "G":
            if has_count:
                target = max(0, min(count - 1, doc.line_count - 1))
            else:
                target = doc.line_count - 1
            self._move_visual_cursor((target, 0))
            return True

        if key in "fFtT":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            return True

        if key in ";," and self._last_char_search:
            motion, target_char = self._last_char_search
            if key == ",":
                motion = motion.swapcase()
            col_offset = 0
            if motion == "t":
                col_offset = 1
            elif motion == "T":
                col_offset = -1
            self._execute_visual_char_search(
                motion, target_char, count, col_offset=col_offset
            )
            return True

        if key == "%":
            match_info = find_matching_bracket(doc, row, col)
            if match_info is not None:
                _bracket_location, match_location = match_info
                self._move_visual_cursor(match_location)
            return True

        if key in "ai":
            self._pending_keys = key
            self._pending_count = count if has_count else None
            return True

        if event.key in ("ctrl+d", "ctrl+u"):
            half = max(1, self.size.height // 2)
            target = min(row + half, doc.line_count - 1)
            if event.key == "ctrl+u":
                target = max(row - half, 0)
            self._move_visual_cursor((target, col))
            return True

        if key in ("d", "x"):
            self._apply_visual_operator("d")
            return True
        if key == "S":
            self._queue_visual_surround()
            return True
        if key in ("c", "s"):
            self._apply_visual_operator("c")
            return True
        if key == "y":
            self._apply_visual_operator("y")
            return True
        if key == "p":
            self._replace_visual_selection_with_register(count)
            return True
        if key in (">", "<"):
            self._apply_visual_indent_operator(key, count)
            return True
        if key == "u":
            self._apply_visual_case_operator("gu")
            return True
        if key == "U":
            self._apply_visual_case_operator("gU")
            return True
        if key == "~":
            self._apply_visual_case_operator("g~")
            return True
        if key in ("*", "#"):
            return bool(self._search_visual_selection(reverse=key == "#", count=count))

        return True


__all__ = ["VimVisualKeyHandlingMixin"]
