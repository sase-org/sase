"""Vim visual-mode operator execution for PromptTextArea."""

from __future__ import annotations

from textual.document._document import Selection

from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.widgets._vim_normal_state import VisualMutation
from sase.ace.tui.widgets._vim_registers import first_non_blank_col
from sase.ace.tui.widgets._vim_transforms import apply_case_operator
from sase.ace.tui.widgets._vim_visual_state import VimVisualStateMixin, VisualKind


class VimVisualOperatorMixin(VimVisualStateMixin):
    """Mixin providing vim visual-mode operator execution."""

    def _store_visual_register(self, text: str, kind: VisualKind) -> None:
        """Store selected text in the unnamed register and system clipboard."""
        self._store_vim_register(text, kind)
        if text:
            copy_to_system_clipboard(text)

    def _visual_selected_text(self) -> tuple[str, VisualKind]:
        """Return selected text and register kind for the current visual mode."""
        if self._visual_kind() == "linewise":
            first, last = self._linewise_visual_rows()
            lines = [self.document.get_line(row) for row in range(first, last + 1)]
            return ("\n".join(lines), "linewise")
        start, end = self._charwise_visual_range()
        return (self._get_text_in_range(start, end), "charwise")

    def _visual_mutation_shape(self, op: str) -> tuple[str, int]:
        """Return visual-repeat kind and same-sized range for *op*."""
        if self._visual_kind() == "linewise":
            first, last = self._linewise_visual_rows()
            return ("linewise", last - first + 1)

        start, end = self._charwise_visual_range()
        if op in {">", "<"}:
            return ("linewise", end[0] - start[0] + 1)
        size = self._absolute_offset(end) - self._absolute_offset(start)
        return ("charwise", max(0, size))

    def _record_visual_mutation(
        self,
        op: str,
        *,
        units: int = 1,
        delimiter: str | None = None,
        shape: tuple[str, int] | None = None,
    ) -> None:
        """Record a visual-mode change for dot-repeat."""
        if self._replaying_dot:
            return
        kind, size = shape if shape is not None else self._visual_mutation_shape(op)
        if size <= 0:
            self._mutation_key_buffer.clear()
            return
        self._last_visual_mutation = VisualMutation(
            op,
            kind,
            size,
            max(1, units),
            delimiter,
        )
        self._last_mutation_keys = []
        self._last_mutation_count = 1
        self._last_mutation_insert = None
        self._mutation_key_buffer.clear()

    def _queue_visual_surround(self) -> None:
        """Snapshot the active visual range and wait for a delimiter key."""
        kind = self._visual_kind()
        if kind == "linewise":
            first, last = self._linewise_visual_rows()
            start = (first, 0)
            end = (last, len(self.document.get_line(last)))
            size = last - first + 1
        else:
            start, end = self._charwise_visual_range()
            size = self._absolute_offset(end) - self._absolute_offset(start)

        if size <= 0 or not self._get_text_in_range(start, end):
            self._pending_visual_surround_range = None
            self._pending_keys = ""
            self._enter_normal_mode()
            return

        self._pending_visual_surround_range = (kind, start, end, size)
        self._pending_keys = "visual-surround"
        self._update_visual_display()

    def _apply_pending_visual_surround(self, key: str) -> None:
        """Apply a delimiter to the saved visual range and return to Normal."""
        target = self._pending_visual_surround_range
        self._pending_visual_surround_range = None
        if target is None:
            self._enter_normal_mode()
            return

        kind, start, end, size = target
        applied = self._apply_surround_to_range(
            key,
            kind,
            start,
            end,
            preserve_boundaries=True,
        )
        if applied:
            self._record_visual_mutation(
                "S",
                delimiter=key,
                shape=(kind, size),
            )
        cursor = self.cursor_location
        self._clear_visual_state(cursor)
        self._enter_normal_mode()

    def _linewise_replacement_payload(self, text: str) -> str:
        """Return replacement text for a linewise visual range."""
        _first, last = self._linewise_visual_rows()
        if text and last < self.document.line_count - 1:
            return text + "\n"
        return text

    def _apply_visual_operator(self, op: str) -> None:
        """Apply a visual operator to the active selection."""
        kind = self._visual_kind()
        if op in {"d", "c"}:
            self._record_visual_mutation(op)
        self._collapse_visual_before_operator()
        if kind == "linewise":
            first, last = self._linewise_visual_rows()
            self._execute_linewise_operator(first, last, op)
            if op == "c":
                return
            if op == "y":
                self.selection = Selection.cursor((first, 0))
            self._enter_normal_mode()
            return

        start, end = self._charwise_visual_range()
        self._execute_charwise_operator(start, end, op)
        if op == "c":
            return
        self._enter_normal_mode()

    def _replace_visual_selection_with_register(self, count: int) -> None:
        """Replace the active visual selection with the unnamed register."""
        count = max(1, count)
        register = self._vim_register
        selected_text, selected_kind = self._visual_selected_text()
        kind = self._visual_kind()
        self._collapse_visual_before_operator()
        self._store_visual_register(selected_text, selected_kind)

        was_readonly = self.read_only
        self.read_only = False
        if kind == "linewise":
            start, end = self._linewise_visual_range()
            insert = "\n".join(register.text.split("\n") * count)
            payload = self._linewise_replacement_payload(insert)
            self._record_mutation()
            self._replace_via_keyboard(payload, start, end)
            self.read_only = was_readonly
            first_line = insert.split("\n", 1)[0] if insert else ""
            cursor = (start[0], first_non_blank_col(first_line))
            self.selection = Selection.cursor(cursor)
            self._enter_normal_mode()
            return

        start, end = self._charwise_visual_range()
        insert = register.text * count
        self._record_mutation()
        self._replace_via_keyboard(insert, start, end)
        self.read_only = was_readonly
        cursor = self._last_char_location_after_insert(start, insert)
        self.selection = Selection.cursor(cursor)
        self._enter_normal_mode()

    def _apply_visual_case_operator(self, op: str) -> None:
        """Apply a case operator over the active visual selection."""
        selected_text, selected_kind = self._visual_selected_text()
        if not selected_text:
            self._clear_visual_state()
            self._enter_normal_mode()
            return
        kind = self._visual_kind()
        self._record_visual_mutation(op)
        self._collapse_visual_before_operator()
        self._store_visual_register(selected_text, selected_kind)
        was_readonly = self.read_only
        self.read_only = False
        if kind == "linewise":
            start, end = self._linewise_visual_range()
            replacement = self._linewise_replacement_payload(
                apply_case_operator(selected_text, op)
            )
        else:
            start, end = self._charwise_visual_range()
            replacement = apply_case_operator(selected_text, op)
        self._record_mutation()
        self._replace_via_keyboard(replacement, start, end)
        self.read_only = was_readonly
        self.selection = Selection.cursor(start)
        self._enter_normal_mode()

    def _apply_visual_indent_operator(self, op: str, count: int) -> None:
        """Apply an indent/dedent operator to the selected lines."""
        count = max(1, count)
        kind = self._visual_kind()
        if kind == "linewise":
            first, last = self._linewise_visual_rows()
        else:
            start, end = self._charwise_visual_range()
            first, last = start[0], end[0]
        self._record_visual_mutation(op, units=count)
        self._collapse_visual_before_operator()
        self._execute_linewise_transform_operator(first, last, op, units=count)
        self.selection = Selection.cursor(self.cursor_location)
        self._enter_normal_mode()


__all__ = ["VimVisualOperatorMixin"]
