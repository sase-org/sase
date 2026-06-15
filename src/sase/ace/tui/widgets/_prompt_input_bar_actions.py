"""Submission, cancellation, and snippet behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_suffix_skeleton,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarActionsMixin(_MixinBase):
    """Prompt submit/cancel actions and snippet insertion helpers."""

    if TYPE_CHECKING:
        Cancelled: Any
        Submitted: Any
        _mode: str

        def active_text_area(self) -> PromptTextArea: ...
        def current_prompt_text(self) -> str: ...

    def _handle_text_submission(self, _text: str) -> None:
        """Process text submission from a pane's TextArea.

        Phase 2 preserves the pre-stack contract: ``<enter>`` submits the whole
        prompt.  The whole stack is joined back into one canonical multi-prompt
        string so dispatch splits it exactly as it did when the bar was a single
        text box.  (Per-pane submit semantics arrive in Phase 4.)
        """
        self.post_message(self.Submitted(self.current_prompt_text(), mode=self._mode))

    def action_cancel(self) -> None:
        """Cancel the input bar."""
        text_area = self.active_text_area()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()
        self.post_message(
            self.Cancelled(cancelled_text=self.current_prompt_text(), mode=self._mode)
        )

    def insert_snippet(
        self,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> None:
        """Insert a snippet reference at the cursor position.

        The '#' from the '#@' trigger is already in the input
        ('@' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
            entry: Optional selected xprompt metadata for smart argument insertion.
        """
        text_area = self.active_text_area()
        start, end = text_area.selection
        if entry is not None and self._insert_xprompt_smart_snippet(
            text_area,
            entry,
            start,
            end,
        ):
            text_area.focus()
            return

        reference_start = max(0, text_area._absolute_offset(start) - 1)
        text_area._replace_via_keyboard(snippet_name, start, end)
        reference_end = reference_start + 1 + len(snippet_name)
        text_area._maybe_show_inserted_xprompt_arg_hint(reference_start, reference_end)
        text_area.focus()

    def _insert_xprompt_smart_snippet(
        self,
        text_area: PromptTextArea,
        entry: XPromptAssistEntry,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> bool:
        """Insert a selected xprompt using the Ctrl+T completion skeleton."""
        skeleton = xprompt_completion_suffix_skeleton(entry)
        if not text_area._expand_snippet_template_at_range(skeleton, start, end):
            return False

        cursor_offset = text_area._absolute_offset(text_area.cursor_location)
        hint = detect_xprompt_arg_hint_at_cursor(
            text_area.text,
            cursor_offset,
            [entry],
        )
        if hint is None:
            text_area._clear_xprompt_arg_hint()
            return True

        text_area._active_xprompt_arg_hint = hint
        text_area._show_xprompt_arg_hint(hint)
        return True
