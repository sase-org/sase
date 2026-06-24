"""PromptTextArea actions, mode transitions, and focus helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.screen import ModalScreen

from sase.ace.tui.widgets._jinja_pair_editing import (
    plan_jinja_delete_left,
    plan_jinja_delete_right,
)
from sase.ace.tui.widgets._paired_text_editing import (
    plan_pair_delete_left,
    plan_pair_delete_right,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
else:
    _MixinBase = object


def prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextAreaActionsMixin(_MixinBase):
    """PromptTextArea action handlers and prompt-bar integration."""

    if TYPE_CHECKING:
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
        _snippet_tabstops: list[int]
        _insert_g_prefix_pending: bool
        _normal_g_prefix_pending: bool
        _vcs_mru_index: int | None
        _vim_mode: str

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None: ...
        def _clear_soft_completion(
            self,
            *,
            cancel_timer: bool = False,
        ) -> None: ...
        def _clear_visual_state(
            self,
            cursor: tuple[int, int] | None = None,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _compute_recursive_finder_context(self) -> Any | None: ...
        def _insert_finder_result(
            self,
            ctx: Any,
            result: CompletionCandidate,
        ) -> None: ...
        def _finish_dot_insert_capture(self) -> None: ...
        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...
        def _sync_vim_cursor_class(self) -> None: ...

    def _find_prompt_bar(self) -> Any:
        """Walk up the widget tree to find the parent PromptInputBar."""
        PromptInputBar = prompt_bar_class()
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                return parent
            parent = parent.parent
        return None

    def _notify_prompt_bar_text_undo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode undo changed this pane's text.

        Lets the bar unstage xprompt inputs an inline expansion auto-staged when
        (and only when) this undo reversed that expansion's body splice. A pane
        with no parent bar -- or an undo that matches no expansion transaction --
        is a no-op.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_undo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _notify_prompt_bar_text_redo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode redo changed this pane's text."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_redo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _show_insert_g_prefix_hints(self) -> None:
        """Reveal prompt-local ``Ctrl+G`` continuation hints for INSERT mode."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show(prefix_label="^G", include_editor=True)

    def _clear_insert_g_prefix(self) -> None:
        """Clear any pending INSERT-mode ``Ctrl+G`` prefix and hide its hints."""
        if not self._insert_g_prefix_pending:
            return
        self._insert_g_prefix_pending = False
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()

    def _show_normal_g_prefix_hints(self) -> None:
        """Reveal prompt-local ``Ctrl+G`` continuation hints for NORMAL mode.

        NORMAL-mode ``Ctrl+G`` shares the INSERT-mode ``Ctrl+G`` hint surface
        (the ``^G`` prefix label and the editor continuation), only differing in
        the vim mode it lives in and the ``target_mode`` it later dispatches.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show(prefix_label="^G", include_editor=True)

    def _clear_normal_g_prefix(self) -> None:
        """Clear any pending NORMAL-mode ``Ctrl+G`` prefix and hide its hints."""
        if not self._normal_g_prefix_pending:
            return
        self._normal_g_prefix_pending = False
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()

    def action_submit_prompt(self) -> None:
        """Submit the prompt text (only the selected pane in a stack)."""
        self._clear_insert_g_prefix()
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_submit_prompt_stack(self) -> None:
        """Submit the whole prompt stack as one multi-prompt (``<ctrl+s>``)."""
        self._clear_insert_g_prefix()
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_whole_stack_submission()

    def action_open_prompt_history(self) -> None:
        """Request prompt history, filtered by the current single-line prompt."""
        bar = self._find_prompt_bar()
        if not bar or bar._mode != "prompt":
            return
        if self.document.line_count != 1:
            return

        self._clear_insert_g_prefix()
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None

        PromptInputBar = prompt_bar_class()
        bar.post_message(
            PromptInputBar.HistoryRequested(
                initial_filter=self.text,
                preserve_prompt_bar=True,
            )
        )

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or end of next line if already there."""
        row, col = self.cursor_location
        line_end = len(self.document.get_line(row))
        if col >= line_end and row < self.document.line_count - 1:
            next_end = len(self.document.get_line(row + 1))
            self.move_cursor((row + 1, next_end), select=select)
        else:
            self.move_cursor((row, line_end), select=select)

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Move to start of line, or start of previous line if already there."""
        row, col = self.cursor_location
        if col == 0 and row > 0:
            self.move_cursor((row - 1, 0), select=select)
        else:
            self.move_cursor((row, 0), select=select)

    def _refresh_completion_after_text_delete(self) -> None:
        """Refresh prompt assist surfaces after TextArea delete actions."""
        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()

    def action_delete_left(self) -> None:
        """Delete left, paired-deleting an empty auto-pair, then refresh menus."""
        if self._try_paired_delete(forward=False):
            return
        super().action_delete_left()
        self._refresh_completion_after_text_delete()

    def action_delete_right(self) -> None:
        """Delete right, paired-deleting an empty auto-pair, then refresh menus."""
        if self._try_paired_delete(forward=True):
            return
        super().action_delete_right()
        self._refresh_completion_after_text_delete()

    def _try_paired_delete(self, *, forward: bool) -> bool:
        """Delete both sides of an empty auto-pair when its opener is removed.

        First tries the Jinja-variable planners so deleting a ``{{ ... }}``
        delimiter brace removes its mirror ``}}`` brace and deleting a boundary
        padding space removes the other boundary space (collapsing ``{{  }}`` to
        ``{{}}``). Falling back to the generic planners, backspacing the opener
        of ``(|)``, ``[|]``, ``{|}``, ``'|'`` (and the other supported
        quote/bracket pairs) or forward-deleting it in ``|()`` removes the
        matching closer too. Returns False (so the default single-character
        delete runs) when there is a selection or the cursor is not adjacent to a
        paired delimiter.
        """
        start, end = self.selection
        if start != end:
            return False
        text = self.text
        offset = self._absolute_offset(self.cursor_location)
        plan = (
            plan_jinja_delete_right(text, offset)
            if forward
            else plan_jinja_delete_left(text, offset)
        )
        if plan is None:
            plan = (
                plan_pair_delete_right(text, offset)
                if forward
                else plan_pair_delete_left(text, offset)
            )
        if plan is None:
            return False
        self._replace_via_keyboard(
            plan.text,
            self._location_from_absolute(plan.start),
            self._location_from_absolute(plan.end),
        )
        self.cursor_location = self._location_from_absolute(plan.cursor)
        self._refresh_completion_after_text_delete()
        return True

    def action_delete_word_left(self) -> None:
        """Delete word-left, then refresh any active completion menu."""
        super().action_delete_word_left()
        self._refresh_completion_after_text_delete()

    def action_delete_word_right(self) -> None:
        """Delete word-right, then refresh any active completion menu."""
        super().action_delete_word_right()
        self._refresh_completion_after_text_delete()

    def action_open_editor(self) -> None:
        """Request to open the external editor (``^G g`` / ``^G ^G``).

        A multi-pane prompt stack opens the whole stack as xprompt markdown (the
        ``AllEditorRequested`` surface); a single-pane bar opens just the current
        prompt. Keypress handling stays light -- clear transient completion /
        arg-hint state and post the message -- while the bar owns serializing the
        stack off the keypress path.
        """
        PromptInputBar = prompt_bar_class()
        bar = self._find_prompt_bar()
        if not bar:
            return
        self._clear_insert_g_prefix()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()
        if bar._mode == "prompt" and bar.is_stacked():
            bar.post_message(PromptInputBar.AllEditorRequested())
            return
        row, col = self.cursor_location
        bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        bar = self._find_prompt_bar()
        if bar and bar._mode == "feedback":
            return
        PromptInputBar = prompt_bar_class()
        if bar:
            self._clear_insert_g_prefix()
            self._clear_soft_completion(cancel_timer=True)
            self._clear_xprompt_arg_hint()
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def _open_recursive_file_finder(self) -> None:
        """Open the recursive fuzzy file finder modal (Ctrl+R).

        Captures the recursive root and prompt token-range, enumerates
        candidates once, and pushes the finder modal. On accept, the selected
        path replaces the captured token range in the prompt.
        """
        from sase.ace.tui.modals.recursive_finder_modal import (
            RecursiveFileFinderModal,
        )
        from sase.ace.tui.widgets.recursive_file_finder import (
            enumerate_recursive_candidates,
        )

        ctx = self._compute_recursive_finder_context()
        if ctx is None:
            return

        candidates, truncated = enumerate_recursive_candidates(
            ctx.root_abs, ctx.root_display
        )
        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)

        def _on_result(result: CompletionCandidate | None) -> None:
            self._refocus_if_needed()
            if result is not None:
                self._insert_finder_result(ctx, result)

        self.app.push_screen(
            RecursiveFileFinderModal(
                root_label=ctx.root_display or "./",
                candidates=candidates,
                truncated=truncated,
                initial_query=ctx.query,
            ),
            _on_result,
        )

    def _open_submit_choice_panel(self) -> None:
        """Open the prompt-stack submit chooser for ambiguous ``<enter>``."""
        from sase.ace.tui.modals.prompt_submit_choice_modal import (
            PromptSubmitChoice,
            PromptSubmitChoiceModal,
        )

        bar = self._find_prompt_bar()
        if bar is None or not bar.is_multi_pane():
            return

        prompt_count = sum(1 for text in bar.all_prompt_texts() if text.strip())
        if prompt_count <= 0:
            return

        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()

        def _on_result(result: PromptSubmitChoice | None) -> None:
            self._refocus_if_needed()
            if result == "all":
                self.action_submit_prompt_stack()
            elif result == "current":
                self.action_submit_prompt()

        self.app.push_screen(
            PromptSubmitChoiceModal(prompt_count=prompt_count),
            _on_result,
        )

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._finish_dot_insert_capture()
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_prompt_search(clear_highlights=True)
        self._clear_visual_state()
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        self._vim_mode = "normal"
        self._clear_soft_completion(cancel_timer=True)
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self._snippet_tabstops = []
        self.read_only = True
        self._sync_vim_cursor_class()
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar._refresh_title("[NORMAL]")
            bar.set_prompt_mode_subtitle(bar.normal_mode_subtitle())

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_prompt_search(clear_highlights=True)
        self._clear_visual_state()
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self.read_only = False
        self._sync_vim_cursor_class()
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar._refresh_title()
            bar.set_prompt_mode_subtitle(bar.insert_mode_subtitle())

    def _on_resize(self) -> None:
        """Scroll cursor into view after the parent resizes."""
        super()._on_resize()
        self.call_after_refresh(self.scroll_cursor_visible)
        bar = self._find_prompt_bar()
        if bar:
            bar._schedule_height_update()

    def on_blur(self) -> None:
        """Schedule a deferred refocus when the text area loses focus."""
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_prompt_search(clear_highlights=True)
        self.call_later(self._refocus_if_needed)

    def _refocus_if_needed(self) -> None:
        """Refocus this text area unless a modal is active or a sibling pane owns it.

        With a multi-pane prompt stack, focus intentionally moves between panes;
        the just-blurred pane must not steal focus back. Only the bar's active
        pane refocuses itself (the single-pane bar always treats itself as
        active), preserving the original "keep the prompt focused" behavior.
        """
        if not self.is_mounted or isinstance(self.app.screen, ModalScreen):
            return
        bar = self._find_prompt_bar()
        if bar is not None:
            # Focus intentionally moved to the frontmatter panel (or its inline /
            # raw editors); let it keep focus instead of snapping back here.
            owns = getattr(bar, "_frontmatter_panel_owns_focus", None)
            if callable(owns) and owns():
                return
            try:
                if bar.active_text_area() is not self:
                    return
            except Exception:
                pass
        self.focus()
