"""Vim normal-mode editing and mode-switch dispatch for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._vim_normal_motions import VimNormalMotionsMixin

if TYPE_CHECKING:
    from sase.ace.tui.widgets._paired_text_editing import TextEdit


class VimNormalEditingMixin(VimNormalMotionsMixin):
    """Mixin for normal-mode edit commands and mode changes."""

    if TYPE_CHECKING:
        _pending_count: int | None
        _pending_keys: str
        _pending_operator: str
        _mutation_count: int

        def _apply_normal_open_line_plan(self, plan: TextEdit) -> None: ...
        def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None: ...
        def _normal_open_above_insert_text(self, row: int) -> str: ...
        def _normal_open_below_insert_text(self, row: int) -> str: ...
        def _normal_open_line_plan(
            self,
            row: int,
            *,
            above: bool,
        ) -> TextEdit | None: ...
        def _update_count_display(self) -> None: ...
        def _record_insert_mutation_start(self, count: int) -> None: ...
        def _notify_host_text_undo(self, before_text: str, after_text: str) -> None: ...
        def _notify_host_text_redo(self, before_text: str, after_text: str) -> None: ...

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
            before = self.text
            self.undo()
            after = self.text
            self.read_only = was_readonly
            self._clear_prompt_search(clear_highlights=True)
            # An undo that reverses a ``Ctrl+I`` inline-expansion splice also
            # unstages the inputs that expansion auto-staged; any other undo is
            # untouched by this notification.
            if after != before:
                self._notify_host_text_undo(before, after)
            return True
        if event.key == "ctrl+r":
            before = self.text
            self._redo()
            after = self.text
            # The mirror of ``u``: redoing an inline-expansion splice restages
            # its auto-staged inputs.
            if after != before:
                self._notify_host_text_redo(before, after)
            return True

        if key == "v":
            self._enter_visual_mode("charwise")
            return True
        if key == "V":
            self._enter_visual_mode("linewise")
            return True
        if key == "i":
            self._enter_insert_mode()
            self._record_insert_mutation_start(count)
            return True
        if key == "a":
            row, col = self.cursor_location
            line = self.document.get_line(row)
            self._enter_insert_mode()
            if col < len(line):
                self.cursor_location = (row, col + 1)
            self._record_insert_mutation_start(count)
            return True
        if key == "A":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            self._record_insert_mutation_start(count)
            return True
        if key == "I":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            col = 0
            while col < len(line) and line[col].isspace():
                col += 1
            self._enter_insert_mode()
            self.cursor_location = (row, col)
            self._record_insert_mutation_start(count)
            return True
        if key == "o":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            # A host planner (the prompt's ordered lists) may need a wider edit
            # than the string hooks allow -- it renumbers the run the new item
            # joins. INSERT mode comes first either way, because
            # ``_replace_via_keyboard`` is a no-op while the pane is read-only.
            plan = self._normal_open_line_plan(row, above=False)
            if plan is not None:
                self._enter_insert_mode()
                self._apply_normal_open_line_plan(plan)
                self._record_insert_mutation_start(count)
                return True
            insert_text = self._normal_open_below_insert_text(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            start, end = self.selection
            self._replace_via_keyboard(insert_text, start, end)
            self._record_insert_mutation_start(count)
            return True
        if key == "O":
            row = self.cursor_location[0]
            plan = self._normal_open_line_plan(row, above=True)
            if plan is not None:
                self._enter_insert_mode()
                self._apply_normal_open_line_plan(plan)
                self._record_insert_mutation_start(count)
                return True
            insert_text = self._normal_open_above_insert_text(row)
            self._enter_insert_mode()
            self.cursor_location = (row, 0)
            start, end = self.selection
            self._replace_via_keyboard(insert_text, start, end)
            self.cursor_location = (row, len(insert_text) - 1)
            self._record_insert_mutation_start(count)
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
            self._mutation_count = max(1, count)
            self._execute_charwise_operator((row, col), (row, len(line)), op)
            return True
        if key == "S":
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + count - 1, self.document.line_count - 1)
            self._mutation_count = max(1, count)
            self._execute_linewise_operator(cur_row, last_row, "c")
            return True

        if key in ("p", "P"):
            self._mutation_count = max(1, count)
            self._paste_vim_register(before=key == "P", count=count)
            return True

        if key in ("x", "s"):
            row, col = self.cursor_location
            line = doc.get_line(row)
            end_col = min(col + count, len(line))
            op = "c" if key == "s" else "d"
            self._mutation_count = max(1, count)
            self._execute_charwise_operator((row, col), (row, end_col), op)
            return True
        if key == "X":
            row, col = self.cursor_location
            start_col = max(0, col - count)
            self._mutation_count = max(1, count)
            self._execute_charwise_operator((row, start_col), (row, col), "d")
            return True
        if key == "r":
            self._pending_keys = "r"
            self._pending_count = count if has_count else None
            self._update_count_display()
            return True
        if not self._pending_operator:
            bracket = {
                "left_square_bracket": "[",
                "right_square_bracket": "]",
            }.get(key, key)
            if bracket in {"[", "]"}:
                self._pending_keys = bracket
                self._pending_count = count if has_count else None
                self._update_count_display()
                return True

        if key == "~":
            self._mutation_count = max(1, count)
            self._toggle_case(count)
            return True
        if event.key in ("ctrl+a", "ctrl+x"):
            self._mutation_count = max(1, count)
            self._apply_number_change(count if event.key == "ctrl+a" else -count)
            return True

        if key == "J":
            self._mutation_count = max(1, count)
            self._join_lines(count)
            return True

        return False
