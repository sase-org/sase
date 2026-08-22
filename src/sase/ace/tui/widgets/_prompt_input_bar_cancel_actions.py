"""Prompt cancellation actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarCancelActionsMixin(_MixinBase):
    """Cancel one prompt pane or the entire input bar."""

    if TYPE_CHECKING:
        Cancelled: Any
        _mode: str
        _stack: PromptStackState

        def active_text_area(self) -> PromptTextArea: ...
        def current_prompt_text(self) -> str: ...
        def _sync_state_from_widgets(self) -> None: ...
        def _clear_active_completion_state(self) -> None: ...
        def _rebuild_stack(
            self,
            enter_mode: str | None = None,
            *,
            restore_focus: PromptFocusRestore | None = None,
        ) -> None: ...
        def _confirm_discard_dirty_snippet(
            self,
            proceed: Callable[[], None],
        ) -> bool: ...
        def close_snippet_target(
            self,
            reason: Literal["saved", "discarded", "replaced"],
        ) -> bool: ...
        def close_mini_xprompt_target(
            self,
            reason: Literal["saved", "discarded", "replaced"],
        ) -> bool: ...

    def action_cancel(self) -> None:
        """Cancel the input bar (``<ctrl+c>``).

        Phase 4: in a multi-pane stack ``<ctrl+c>`` cancels only the selected
        pane — its text is recorded as cancelled history and the pane is removed
        while the bar stays mounted.  In a single-pane bar (or feedback /
        approve-prompt mode) the whole bar is dismissed as before.
        """
        text_area = self.active_text_area()
        text_area._clear_insert_g_prefix()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()

        if self._mode == "prompt" and len(self._stack) > 1:
            self._sync_state_from_widgets()
            if self._stack.selected_item.is_snippet_pane:

                def _close_snippet() -> None:
                    self.close_snippet_target("discarded")

                self._confirm_discard_dirty_snippet(_close_snippet)
                return
            if self._stack.selected_item.is_mini_xprompt_pane:

                def _close_mini_xprompt() -> None:
                    self.close_mini_xprompt_target("discarded")

                self._confirm_discard_dirty_snippet(_close_mini_xprompt)
                return
            cancelled_text = self._stack.selected_item.text.strip()
            removed = self._stack.remove_selected()
            if not removed:

                def _cancel_bar() -> None:
                    self.post_message(
                        self.Cancelled(
                            cancelled_text=self.current_prompt_text(),
                            mode=self._mode,
                        )
                    )

                if self._stack.has_auxiliary_pane:
                    self._confirm_discard_dirty_snippet(_cancel_bar)
                else:
                    _cancel_bar()
                return
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

    def action_cancel_all(self) -> None:
        """Cancel the whole prompt stack as one history entry."""
        if self._mode != "prompt":
            self.action_cancel()
            return

        def _cancel_all() -> None:
            self._sync_state_from_widgets()
            self._clear_active_completion_state()
            self.post_message(
                self.Cancelled(
                    cancelled_text=self.current_prompt_text(),
                    mode=self._mode,
                    keep_bar=False,
                    record_segments=False,
                )
            )

        self._confirm_discard_dirty_snippet(_cancel_all)
