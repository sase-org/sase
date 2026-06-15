"""Submission, cancellation, and snippet behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.prompt_stack import PromptStackState
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
        _stack: PromptStackState

        def active_text_area(self) -> PromptTextArea: ...
        def current_prompt_text(self) -> str: ...
        def _sync_state_from_widgets(self) -> None: ...
        def _clear_active_completion_state(self) -> None: ...
        def _rebuild_stack(self, enter_mode: str | None = None) -> None: ...

    def _handle_text_submission(self, _text: str) -> None:
        """Process an ``<enter>`` submission from a pane's TextArea.

        Phase 4: ``<enter>`` submits only the *selected* pane.  In a single-pane
        bar (or feedback / approve-prompt mode, which are never stacks) this is
        the pre-stack contract — the whole bar is submitted and the app unmounts
        it.  In a multi-pane stack the selected pane is launched while the bar
        stays mounted (``keep_bar``) so the remaining panes can be submitted in
        turn; an empty selected pane is simply dropped instead of launched.
        """
        self._sync_state_from_widgets()
        if self._mode != "prompt" or len(self._stack) <= 1:
            self.post_message(
                self.Submitted(self.current_prompt_text(), mode=self._mode)
            )
            return

        selected_text = self._stack.selected_item.text.strip()
        self._stack.remove_selected()
        self._clear_active_completion_state()
        if selected_text:
            self.post_message(
                self.Submitted(selected_text, mode=self._mode, keep_bar=True)
            )
        self._rebuild_stack(enter_mode="insert")

    def _handle_whole_stack_submission(self) -> None:
        """Submit the whole stack as one multi-prompt (``<shift+enter>``/``^S``).

        Only meaningful in prompt mode — feedback / approve-prompt bars are not
        multi-agent surfaces — so it is a no-op elsewhere.  The non-empty panes
        are joined with ``\\n---\\n`` and handed to the app, which unmounts the
        bar and routes the joined text through the existing multi-prompt /
        multi-agent xprompt launch rules.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        self.post_message(
            self.Submitted(
                self.current_prompt_text(), mode=self._mode, whole_stack=True
            )
        )

    def action_cancel(self) -> None:
        """Cancel the input bar (``<ctrl+c>``).

        Phase 4: in a multi-pane stack ``<ctrl+c>`` cancels only the selected
        pane — its text is recorded as cancelled history and the pane is removed
        while the bar stays mounted.  In a single-pane bar (or feedback /
        approve-prompt mode) the whole bar is dismissed as before.
        """
        text_area = self.active_text_area()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()

        if self._mode == "prompt" and len(self._stack) > 1:
            self._sync_state_from_widgets()
            cancelled_text = self._stack.selected_item.text.strip()
            self._stack.remove_selected()
            self._clear_active_completion_state()
            self.post_message(
                self.Cancelled(
                    cancelled_text=cancelled_text, mode=self._mode, keep_bar=True
                )
            )
            self._rebuild_stack(enter_mode="insert")
            return

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
