"""PromptTextArea auto-pairing and planned text-edit application.

Jinja delimiter pairing, bracket/quote auto-pairs, alternation-separator
normalization, and the shared :class:`TextEdit` apply path live here, below
the key dispatcher in
:mod:`~sase.ace.tui.widgets._prompt_text_area_key_handling`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from sase.ace.tui.widgets._alt_syntax_editing import (
    plan_alt_brace_pair,
    plan_alt_separator,
)
from sase.ace.tui.widgets._paired_text_editing import (
    TextEdit,
    plan_pair_close_skip,
    plan_pair_insert,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptTextAreaKeyPairingMixin(_MixinBase):
    """Auto-pair Jinja / brackets / quotes and apply planned text edits."""

    if TYPE_CHECKING:
        _dot_insert_capture_offset: int | None

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_soft_completion(
            self,
            *,
            cancel_timer: bool = False,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _on_prompt_completion_context_changed(self) -> None: ...
        def _open_auto_reference_completion_after_change(
            self,
            character: str | None,
        ) -> None: ...
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...

    def _try_jinja_auto_pair(self, event: Key) -> bool:
        """Auto-pair Jinja delimiters after the second opener character.

        Generic ``{`` pairing already turned the first brace into ``{|}``, so
        the common path consumes that auto-inserted ``}`` and rebuilds it as the
        full Jinja pair. A literal first ``{`` followed by whitespace/EOF (a
        manually-authored buffer or undo/redo state) is still handled so the
        behavior matches whatever brace context the user is sitting in.
        """
        if event.character not in ("{", "%", "#"):
            return False
        start, end = self.selection
        if start != end:
            return False
        row, col = self.cursor_location
        if col <= 0:
            return False
        line = self.document.get_line(row)
        if line[col - 1] != "{":
            return False

        # ``{|}``: generic pairing inserted the closing brace; consume it and
        # rebuild the whole delimiter so the final cursor sits mid-pair.
        if col < len(line) and line[col] == "}":
            bodies = {"{": "{{  }}", "%": "{%  %}", "#": "{#  #}"}
            body = bodies[event.character]
            self._replace_via_keyboard(body, (row, col - 1), (row, col + 1))
            self.cursor_location = (row, col - 1 + 3)
            self._clear_soft_completion(cancel_timer=True)
            self._clear_file_completion()
            self._clear_xprompt_arg_hint()
            self._on_prompt_completion_context_changed()
            return True

        # Literal first ``{`` with nothing (or whitespace) following it.
        if col < len(line) and not line[col].isspace():
            return False
        pairs = {
            "{": ("{  }}", 2),
            "%": ("%  %}", 2),
            "#": ("#  #}", 2),
        }
        insert, cursor_delta = pairs[event.character]
        self._replace_via_keyboard(insert, (row, col), (row, col))
        self.cursor_location = (row, col + cursor_delta)
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
        return True

    def _try_prompt_text_pair_edit(self, event: Key) -> bool:
        """Auto-pair brackets/quotes and normalize ``|`` separators.

        Dispatch order for the typed character: ``|`` runs alternation separator
        normalization inside a live ``%{...}`` span; a closer that already sits
        under the cursor moves over instead of duplicating (close-skip); an
        opener inserts its matching closer at a safe position. Returns False
        (letting the default insertion path run) for every other key, when there
        is an active selection, or when the cursor is not in an applicable
        position.
        """
        char = event.character
        if not char or len(char) != 1:
            return False
        start, end = self.selection
        if start != end:
            return False
        text = self.text
        offset = self._absolute_offset(self.cursor_location)
        if char == "|":
            plan = plan_alt_separator(text, offset)
        else:
            plan = plan_pair_close_skip(text, offset, char)
            if plan is None and char == "{":
                plan = plan_alt_brace_pair(text, offset)
            if plan is None:
                plan = plan_pair_insert(text, offset, char)
        if plan is None:
            return False
        self._apply_planned_text_edit(plan)
        if char == "(":
            self._open_auto_reference_completion_after_change(char)
        return True

    def _apply_planned_text_edit(
        self,
        plan: TextEdit,
        *,
        remap_dot_capture: bool = False,
    ) -> None:
        """Apply a :class:`TextEdit` and clear transient completion state."""
        if remap_dot_capture:
            capture = self._dot_insert_capture_offset
            if capture is not None and capture >= plan.start:
                if capture <= plan.end:
                    # The capture sits inside the rewritten span, so follow the
                    # cursor: a list shift moves both by the same amount, and
                    # the text between them survives the edit untouched.
                    cursor_before = self._absolute_offset(self.cursor_location)
                    capture = max(
                        plan.start,
                        plan.cursor - (cursor_before - capture),
                    )
                else:
                    capture += len(plan.text) - (plan.end - plan.start)
                self._dot_insert_capture_offset = max(0, capture)
        self._replace_via_keyboard(
            plan.text,
            self._location_from_absolute(plan.start),
            self._location_from_absolute(plan.end),
        )
        self.cursor_location = self._location_from_absolute(plan.cursor)
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
