"""Vim normal-mode operator state helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.widgets._vim_registers import VimRegister, VimRegisterKind

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


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
        _last_mutation_keys: list[str]
        _replaying_dot: bool
        _last_char_search: tuple[str, str] | None
        _vim_register: VimRegister

        def _find_prompt_bar(self) -> Any: ...

        def _enter_insert_mode(self) -> None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _handle_normal_mode_key(self, event: Key) -> bool: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...

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
        """Update border subtitle to show the pending count/operator."""
        bar = self._find_prompt_bar()
        if bar:
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
            # Derive the base from the bar so a stacked prompt keeps advertising
            # its stack keymaps while a count/operator/``g`` prefix is pending,
            # instead of flipping back to the single-pane hints.
            base = "[Esc] clear  [i] insert  [^C] cancel"
            getter = getattr(bar, "normal_mode_subtitle", None)
            if callable(getter):
                base = getter()
            subtitle = f"{base}  {indicator}" if indicator else base
            setter = getattr(bar, "set_prompt_mode_subtitle", None)
            if callable(setter):
                setter(subtitle)
            else:
                bar.border_subtitle = subtitle
            if self._pending_keys == "g":
                show_hints = getattr(bar, "show_g_prefix_hints", None)
                if callable(show_hints):
                    show_hints()
            else:
                hide_hints = getattr(bar, "hide_g_prefix_hints", None)
                if callable(hide_hints):
                    hide_hints()

    def _clear_count_prefix(self) -> None:
        """Clear count prefix and update display if needed."""
        if self._count_prefix:
            self._count_prefix = ""
            self._update_count_display()

    def _record_mutation(self) -> None:
        """Record the current key buffer as the last mutation for dot-repeat."""
        if not self._replaying_dot and self._mutation_key_buffer:
            self._last_mutation_keys = list(self._mutation_key_buffer)
        self._mutation_key_buffer.clear()

    def _replay_dot(self, count: int) -> None:
        """Replay the last recorded mutation *count* times."""
        if not self._last_mutation_keys:
            return
        keys = list(self._last_mutation_keys)
        self._replaying_dot = True
        try:
            for _ in range(count):
                for char in keys:
                    self._handle_normal_mode_key(Key(char, char))
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
