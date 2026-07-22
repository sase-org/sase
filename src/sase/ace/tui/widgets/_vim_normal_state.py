"""Vim normal-mode operator state helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from textual.events import Key

from sase.ace.tui.widgets._vim_registers import VimRegister, VimRegisterKind

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class VisualMutation(NamedTuple):
    """A repeatable mutation captured from a visual selection."""

    operation: str
    kind: str
    size: int
    units: int
    delimiter: str | None = None


class VimNormalStateMixin(_MixinBase):
    """Mixin providing vim normal-mode operator state helpers."""

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _vim_mode: str
        _pending_keys: str
        _count_prefix: str
        _pending_count: int | None
        _pending_operator: str
        _pending_operator_count: int
        _pending_surround_range: tuple[str, tuple[int, int], tuple[int, int]] | None
        _pending_change_surround_locations: (
            tuple[
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
            ]
            | None
        )
        _mutation_key_buffer: list[str]
        _mutation_count: int
        _last_mutation_keys: list[str]
        _last_mutation_count: int
        _last_mutation_insert: str | None
        _last_visual_mutation: VisualMutation | None
        _dot_insert_capture_offset: int | None
        _replaying_dot: bool
        _last_char_search: tuple[str, str] | None
        _vim_register: VimRegister

        def _update_vim_mode_display(self, indicator: str = "") -> None: ...

        def _show_pending_g_hints(self) -> None: ...

        def _hide_pending_g_hints(self) -> None: ...

        def _enter_normal_mode(self) -> None: ...

        def _enter_insert_mode(self) -> None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _handle_normal_mode_key(self, event: Key) -> bool: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...

        def _normalize_normal_open_below_replay_text(
            self,
            insert_text: str,
        ) -> str: ...

        def _execute_charwise_operator(
            self,
            start: tuple[int, int],
            end: tuple[int, int],
            op: str,
        ) -> None: ...

        def _execute_charwise_case_operator(
            self,
            start: tuple[int, int],
            end: tuple[int, int],
            op: str,
        ) -> None: ...

        def _execute_linewise_operator(
            self,
            first_row: int,
            last_row: int,
            op: str,
        ) -> None: ...

        def _execute_linewise_transform_operator(
            self,
            first_row: int,
            last_row: int,
            op: str,
            *,
            units: int = 1,
        ) -> None: ...

        def _last_char_location_after_insert(
            self,
            start: tuple[int, int],
            text: str,
        ) -> tuple[int, int]: ...

        def _apply_surround_to_range(
            self,
            key: str,
            kind: str,
            start: tuple[int, int],
            end: tuple[int, int],
            *,
            preserve_boundaries: bool,
        ) -> bool: ...

    # -- Mixin implementation --

    def _is_case_operator(self, op: str) -> bool:
        """Return whether *op* is a vim case operator."""
        return op in {"gu", "gU", "g~"}

    def _is_indent_operator(self, op: str) -> bool:
        """Return whether *op* is a vim indent/dedent operator."""
        return op in {">", "<"}

    def _is_line_repeat_key(self, op: str, key: str) -> bool:
        """Return whether *key* completes an operator's linewise form."""
        if op == "ys":
            return key == "s"
        if op in {"d", "c", "y", ">", "<"}:
            return key == op
        return (op, key) in {("gu", "u"), ("gU", "U"), ("g~", "~")}

    def _update_count_display(self) -> None:
        """Refresh the mode display with the pending count/operator indicator.

        The indicator string is computed here (pure vim state) and handed to the
        host ``_update_vim_mode_display`` hook, which renders it however the host
        wants (the prompt bar's subtitle, or the widget's own border). The
        ``g``-prefix hint surface is likewise delegated to host hooks.
        """
        indicator = ""
        if self._pending_operator:
            if self._pending_operator_count > 1:
                indicator += str(self._pending_operator_count)
            indicator += self._pending_operator
        if self._pending_keys:
            if self._pending_count is not None:
                indicator += str(self._pending_count)
            if self._pending_keys == "surround":
                indicator += "ys"
            elif self._pending_keys == "delete-surround":
                indicator += "ds"
            elif self._pending_keys in {
                "change-surround-old",
                "change-surround-new",
            }:
                indicator += "cs"
            else:
                indicator += self._pending_keys
        if self._count_prefix:
            indicator += self._count_prefix
        self._update_vim_mode_display(indicator)
        if self._pending_keys == "g":
            self._show_pending_g_hints()
        else:
            self._hide_pending_g_hints()

    def _clear_count_prefix(self) -> None:
        """Clear count prefix and update display if needed."""
        if self._count_prefix:
            self._count_prefix = ""
            self._update_count_display()

    def _record_mutation(self) -> None:
        """Record the current key buffer as the last mutation for dot-repeat."""
        if not self._replaying_dot and self._mutation_key_buffer:
            self._last_mutation_keys = list(self._mutation_key_buffer)
            self._last_mutation_count = max(1, self._mutation_count)
            self._last_mutation_insert = None
            self._last_visual_mutation = None
        self._mutation_key_buffer.clear()
        self._mutation_count = 1

    def _record_insert_mutation_start(self, count: int) -> None:
        """Record an insert-style change and begin capturing inserted text."""
        if self._replaying_dot:
            return
        self._mutation_count = max(1, count)
        self._record_mutation()
        self._start_dot_insert_capture()

    def _start_dot_insert_capture(self) -> None:
        """Mark the current cursor offset as the start of insert-text capture."""
        if not self._replaying_dot:
            self._dot_insert_capture_offset = self._absolute_offset(
                self.cursor_location
            )

    def _finish_dot_insert_capture(self) -> None:
        """Finish an insert-text capture when INSERT mode exits."""
        start_offset = self._dot_insert_capture_offset
        if start_offset is None:
            return
        self._dot_insert_capture_offset = None
        if self._replaying_dot:
            return

        end_offset = self._absolute_offset(self.cursor_location)
        if end_offset < start_offset:
            self._last_mutation_insert = ""
            return

        text = self.text
        start_offset = max(0, min(start_offset, len(text)))
        end_offset = max(0, min(end_offset, len(text)))
        self._last_mutation_insert = text[start_offset:end_offset]

    def _dot_insert_repeats_text(self, keys: list[str]) -> bool:
        """Return whether a replay count should multiply captured insert text."""
        return bool(keys) and keys[0] in {"i", "a", "A", "I", "o", "O"}

    def _insert_replayed_text_and_return_normal(self, payload: str) -> None:
        """Insert replayed text, leave INSERT mode, and place the cursor."""
        insert_at, replace_end = self.selection
        if payload:
            self._replace_via_keyboard(payload, insert_at, replace_end)
            cursor = self._last_char_location_after_insert(insert_at, payload)
        else:
            cursor = insert_at
        self._enter_normal_mode()
        self.cursor_location = cursor

    def _visual_dot_char_range(
        self,
        size: int,
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return a charwise visual-repeat range from the current cursor."""
        start = self.cursor_location
        start_offset = self._absolute_offset(start)
        end_offset = min(start_offset + max(0, size), len(self.text))
        return (start, self._location_from_absolute(end_offset))

    def _visual_dot_line_rows(self, size: int) -> tuple[int, int]:
        """Return linewise visual-repeat rows from the current cursor."""
        first_row = self.cursor_location[0]
        last_row = min(first_row + max(1, size) - 1, self.document.line_count - 1)
        return (first_row, last_row)

    def _replay_visual_dot(self, count: int, has_count: bool) -> None:
        """Replay a structured visual-mode mutation over a same-sized range."""
        change = self._last_visual_mutation
        if change is None:
            return
        op, kind, size, units, delimiter = change
        if has_count:
            size *= max(1, count)

        self._replaying_dot = True
        try:
            if kind == "linewise":
                first_row, last_row = self._visual_dot_line_rows(size)
                if op == "S" and delimiter is not None:
                    self._apply_surround_to_range(
                        delimiter,
                        "linewise",
                        (first_row, 0),
                        (last_row, len(self.document.get_line(last_row))),
                        preserve_boundaries=True,
                    )
                elif op in {"d", "c"}:
                    self._execute_linewise_operator(first_row, last_row, op)
                elif self._is_indent_operator(op) or self._is_case_operator(op):
                    self._execute_linewise_transform_operator(
                        first_row,
                        last_row,
                        op,
                        units=max(1, units),
                    )
            else:
                start, end = self._visual_dot_char_range(size)
                if op == "S" and delimiter is not None:
                    self._apply_surround_to_range(
                        delimiter,
                        "charwise",
                        start,
                        end,
                        preserve_boundaries=True,
                    )
                elif op in {"d", "c"}:
                    self._execute_charwise_operator(start, end, op)
                elif self._is_case_operator(op):
                    self._execute_charwise_case_operator(start, end, op)

            if (
                op == "c"
                and self._last_mutation_insert is not None
                and self._vim_mode == "insert"
            ):
                self._insert_replayed_text_and_return_normal(self._last_mutation_insert)
        finally:
            self._replaying_dot = False

    def _replay_dot(self, count: int, has_count: bool) -> None:
        """Replay the last recorded mutation with vim count-override semantics."""
        if self._last_visual_mutation is not None:
            self._replay_visual_dot(count, has_count)
            return
        if not self._last_mutation_keys:
            return
        keys = list(self._last_mutation_keys)
        effective_count = max(1, count if has_count else self._last_mutation_count)
        insert_text = self._last_mutation_insert
        repeats_insert_text = insert_text is not None and self._dot_insert_repeats_text(
            keys
        )
        replay_keys = list(keys)
        if effective_count > 1 and not repeats_insert_text:
            replay_keys = [*str(effective_count), *replay_keys]

        self._replaying_dot = True
        try:
            for char in replay_keys:
                self._handle_normal_mode_key(Key(char, char))
            if insert_text is not None and self._vim_mode == "insert":
                if keys[0] == "o":
                    insert_text = self._normalize_normal_open_below_replay_text(
                        insert_text
                    )
                payload = (
                    insert_text * effective_count
                    if repeats_insert_text
                    else insert_text
                )
                self._insert_replayed_text_and_return_normal(payload)
        finally:
            self._replaying_dot = False

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
        self._mutation_count = max(1, op_count * count)
        self._update_count_display()
        return (op, op_count * count)

    def _get_text_in_range(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> str:
        """Extract text between two ``(row, col)`` positions."""
        doc = self.document
        if start[0] == end[0]:
            return doc.get_line(start[0])[start[1] : end[1]]
        parts = [doc.get_line(start[0])[start[1] :]]
        for row in range(start[0] + 1, end[0]):
            parts.append(doc.get_line(row))
        parts.append(doc.get_line(end[0])[: end[1]])
        return "\n".join(parts)

    def _store_vim_register(self, text: str, kind: VimRegisterKind) -> None:
        """Store text in the internal unnamed Vim register."""
        self._vim_register = VimRegister(text=text, kind=kind)
