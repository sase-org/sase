"""Vim normal-mode surround operation helpers."""

from __future__ import annotations

from sase.ace.tui.widgets._vim_normal_state import VimNormalStateMixin
from sase.ace.tui.widgets._vim_text_objects import (
    find_quote_or_bracket_text_object,
    is_quote_or_bracket_text_object_key,
    location_after_char,
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


class VimNormalSurroundMixin(VimNormalStateMixin):
    """Mixin providing vim-surround normal-mode helpers."""

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

    def _apply_pending_surround(self, key: str) -> bool:
        """Wrap the pending ``ys`` target with the delimiter from *key*."""
        target = self._pending_surround_range
        self._pending_surround_range = None
        if target is None:
            self._mutation_key_buffer.clear()
            return False

        kind, start, end = target
        return self._apply_surround_to_range(
            key,
            kind,
            start,
            end,
            preserve_boundaries=False,
        )

    def _apply_surround_to_range(
        self,
        key: str,
        kind: str,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        preserve_boundaries: bool,
    ) -> bool:
        """Wrap a resolved range, optionally preserving its exact boundaries."""
        delimiters = self._surround_delimiters(key)
        if delimiters is None:
            self._mutation_key_buffer.clear()
            return False

        if start > end:
            start, end = end, start
        text = self._get_text_in_range(start, end)
        if not text:
            self._mutation_key_buffer.clear()
            return False

        open_delim, close_delim = delimiters
        if kind == "charwise" and not preserve_boundaries:
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
        return True

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

    def _queue_pending_change_surround(self, key: str, count: int = 1) -> None:
        """Remember a resolved ``cs`` target while waiting for a new delimiter."""
        locations = self._surround_locations(key, count)
        if locations is None:
            self._pending_change_surround_locations = None
            self._mutation_key_buffer.clear()
            return
        self._pending_change_surround_locations = locations
        self._pending_keys = "change-surround-new"
        self._update_count_display()

    def _change_pending_surround(self, key: str) -> None:
        """Change the pending ``cs`` target to the delimiter from *key*."""
        target = self._pending_change_surround_locations
        self._pending_change_surround_locations = None
        delimiters = self._surround_delimiters(key)
        if target is None or delimiters is None:
            self._mutation_key_buffer.clear()
            return

        open_loc, inner_start, close_loc, outer_end = target
        inner_text = self._get_text_in_range(inner_start, close_loc)
        open_delim, close_delim = delimiters
        replacement = f"{open_delim}{inner_text}{close_delim}"
        cursor_offset = self._absolute_offset(self.cursor_location)

        self._record_mutation()
        was_readonly = self.read_only
        self.read_only = False
        self._replace_via_keyboard(replacement, open_loc, outer_end)
        self.read_only = was_readonly
        self.cursor_location = self._location_from_absolute(cursor_offset)

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
            return self._same_char_surround_locations(open_delim, count)
        return self._paired_surround_locations(key, open_delim, close_delim, count)

    def _same_char_surround_locations(
        self,
        delimiter: str,
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
        """Find a same-character delimiter pair enclosing the cursor.

        Pairs the *count*-th unescaped delimiter before the cursor with the
        *count*-th unescaped delimiter after it. Count ``1`` selects the
        nearest enclosing pair; higher counts select successively outer pairs,
        which is how doubled delimiters such as ``""foobar""`` are reached.
        """
        row, col = self.cursor_location
        line = self.document.get_line(row)
        positions = [
            index
            for index, char in enumerate(line)
            if char == delimiter and not self._is_escaped_delimiter(line, index)
        ]
        before = [index for index in positions if index < col]
        after = [index for index in positions if index > col]
        count = max(1, count)
        if len(before) < count or len(after) < count:
            return None

        open_col = before[-count]
        close_col = after[count - 1]
        open_loc = (row, open_col)
        inner_start = (row, open_col + 1)
        close_loc = (row, close_col)
        outer_end = (row, close_col + 1)
        return (open_loc, inner_start, close_loc, outer_end)

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
