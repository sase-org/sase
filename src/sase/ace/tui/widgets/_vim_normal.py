"""Vim normal-mode key handling mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._vim_normal_editing import VimNormalEditingMixin
from sase.ace.tui.widgets._vim_search import SearchDirection


class VimNormalModeMixin(VimNormalEditingMixin):
    """Mixin providing vim normal-mode key handling.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:

        def _clear_search_highlights(self, *, refresh: bool = True) -> None: ...
        def _start_prompt_search(self, direction: SearchDirection) -> None: ...

    def _can_start_prompt_search_from_normal_key(self) -> bool:
        """Return whether ``/`` / ``?`` may open prompt search right now.

        Bare ``/`` and ``?`` open the incremental search command line, but only
        as top-level NORMAL commands. While a multi-key Vim sequence is still
        waiting for its next key, the slash/question mark must instead reach the
        pending handler so literal char-target motions keep working:

        - ``_pending_keys`` holds a motion prefix (``f``/``F``/``t``/``T``), a
          surround/replace prefix, etc. that consumes the next key as data, so
          ``dt/`` deletes up to the literal ``/`` rather than opening search.
        - ``_pending_operator`` is mid-composition (``d``/``c``/``y``/...); the
          next key belongs to that operator, not to a fresh search.
        - ``_count_prefix`` is buffering a count that still awaits its command.
        """
        return not (self._pending_keys or self._pending_operator or self._count_prefix)

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

        if (
            key in {"/", "?"} or event.key in {"slash", "question_mark"}
        ) and self._can_start_prompt_search_from_normal_key():
            direction: SearchDirection = (
                "reverse" if key == "?" or event.key == "question_mark" else "forward"
            )
            self._start_prompt_search(direction)
            return True

        if not self._replaying_dot:
            if (
                not self._pending_operator
                and not self._pending_keys
                and not self._count_prefix
            ):
                self._mutation_key_buffer.clear()
                self._mutation_count = 1
            self._mutation_key_buffer.append(key)

        if event.key == "escape":
            self._pending_keys = ""
            self._pending_count = None
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._pending_surround_range = None
            self._pending_change_surround_locations = None
            self._clear_search_highlights()
            self._clear_count_prefix()
            self._update_count_display()
            return True

        if self._pending_keys:
            return self._handle_normal_pending_key(key, event)

        if key in "123456789" or (key == "0" and self._count_prefix):
            if not self._replaying_dot and self._mutation_key_buffer:
                self._mutation_key_buffer.pop()
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
            self._replay_dot(count, has_count)
            return True

        if self._pending_operator and self._is_line_repeat_key(
            self._pending_operator, key
        ):
            op = self._pending_operator
            op_count = self._pending_operator_count
            self._pending_operator = ""
            self._pending_operator_count = 1
            total = op_count * count
            self._mutation_count = max(1, total)
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
