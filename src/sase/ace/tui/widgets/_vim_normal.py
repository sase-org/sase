"""Vim normal-mode key handling mixin for PromptTextArea."""

from __future__ import annotations

from textual.events import Key

from sase.ace.tui.widgets._vim_normal_editing import VimNormalEditingMixin


class VimNormalModeMixin(VimNormalEditingMixin):
    """Mixin providing vim normal-mode key handling.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

        if not self._replaying_dot:
            if (
                not self._pending_operator
                and not self._pending_keys
                and not self._count_prefix
            ):
                self._mutation_key_buffer.clear()
            self._mutation_key_buffer.append(key)

        if event.key == "escape":
            self._pending_keys = ""
            self._pending_count = None
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._pending_surround_range = None
            self._pending_change_surround_locations = None
            self._clear_count_prefix()
            self._update_count_display()
            return True

        if self._pending_keys:
            return self._handle_normal_pending_key(key, event)

        if key in "123456789" or (key == "0" and self._count_prefix):
            self._count_prefix += key
            self._update_count_display()
            return True

        has_count = bool(self._count_prefix)
        count = int(self._count_prefix) if self._count_prefix else 1
        self._clear_count_prefix()

        if self._pending_operator in {"c", "d", "y"} and key == "s":
            if has_count:
                self._pending_operator_count *= count
            if self._pending_operator == "y":
                self._pending_operator = "ys"
            elif self._pending_operator == "d":
                self._pending_keys = "delete-surround"
                self._pending_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
            else:
                self._pending_keys = "change-surround-old"
                self._pending_count = self._pending_operator_count
                self._pending_operator = ""
                self._pending_operator_count = 1
            self._update_count_display()
            return True

        if key == ".":
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._update_count_display()
            self._mutation_key_buffer.clear()
            self._replay_dot(count)
            return True

        if self._pending_operator and self._is_line_repeat_key(
            self._pending_operator, key
        ):
            op = self._pending_operator
            op_count = self._pending_operator_count
            self._pending_operator = ""
            self._pending_operator_count = 1
            total = op_count * count
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + total - 1, self.document.line_count - 1)
            self._execute_linewise_operator(cur_row, last_row, op)
            self._update_count_display()
            return True

        if key in ("d", "c", "y", ">", "<") and not self._pending_operator:
            self._pending_operator = key
            self._pending_operator_count = count
            self._update_count_display()
            return True

        if self._handle_normal_motion_key(key, event, count, has_count):
            return True

        if self._handle_normal_edit_key(key, event, count, has_count):
            return True

        return False
