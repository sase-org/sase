"""PromptTextArea actions, mode transitions, and focus helpers.

Composes the prompt pane's action mixin chain and adds its top layer: prompt
submission, history / editor / finder requests, the vim mode transitions, and
the focus lifecycle. The lower layers live in
:mod:`~sase.ace.tui.widgets._prompt_text_area_edit_actions` (cursor and delete
actions), :mod:`~sase.ace.tui.widgets._prompt_text_area_list_editing` (prompt
list continuation), and :mod:`~sase.ace.tui.widgets._prompt_text_area_bar` (the
parent ``PromptInputBar`` bridge).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.screen import ModalScreen

from sase.ace.tui.widgets._prompt_text_area_bar import prompt_bar_class
from sase.ace.tui.widgets._prompt_text_area_edit_actions import (
    PromptTextAreaEditActionsMixin,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptTextAreaActionsMixin(PromptTextAreaEditActionsMixin):
    """PromptTextArea action handlers and prompt-bar integration."""

    if TYPE_CHECKING:
        _snippet_tabstops: list[int]
        _vcs_mru_index: int | None

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
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _compute_recursive_finder_context(self) -> Any | None: ...
        def _insert_finder_result(
            self,
            ctx: Any,
            result: CompletionCandidate,
        ) -> None: ...

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
            bar._handle_text_submission(self.text, self)

    def action_submit_prompt_stack(self) -> None:
        """Submit the whole prompt stack as one multi-prompt via the chooser."""
        self._clear_insert_g_prefix()
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_whole_stack_submission(self)

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
                origin_bar=bar,
                origin_text_area=cast("PromptTextArea", self),
                origin_pane_id=self.id or "",
            )
        )

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
        """Switch to vim NORMAL mode, clearing prompt-only transient UI.

        Extends :class:`VimTextArea`'s generic transition (mode / read-only /
        cursor state plus the mode-display refresh routed through the bar) with
        the prompt-only teardown: the ``Ctrl+G`` prefixes, incremental search,
        completion menus, xprompt hints, snippet tabstops, and VCS MRU cycling.
        None of these touch the bar subtitle, so the base's display refresh
        stays authoritative.
        """
        super()._enter_normal_mode()
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_prompt_search(clear_highlights=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        self._clear_soft_completion(cancel_timer=True)
        self._snippet_tabstops = []

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode, clearing the prompt prefix / search UI."""
        super()._enter_insert_mode()
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_prompt_search(clear_highlights=True)

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
