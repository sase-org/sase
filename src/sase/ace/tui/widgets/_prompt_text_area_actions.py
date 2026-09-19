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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from textual.screen import ModalScreen

from sase.ace.tui.widgets._prompt_text_area_bar import prompt_bar_class
from sase.ace.tui.widgets._prompt_text_area_edit_actions import (
    PromptTextAreaEditActionsMixin,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


@dataclass(frozen=True, slots=True)
class _SubmitChoicePaneOrigin:
    item_id: str
    text: str
    role: str


@dataclass(frozen=True, slots=True)
class _SubmitChoiceOrigin:
    bar: Any
    stack: Any
    mode: str
    generation: int
    selected_index: int
    selected_item_id: str
    frontmatter: str
    binding: object | None
    readonly_target: object | None
    target_generation: int
    panes: tuple[_SubmitChoicePaneOrigin, ...]


class PromptTextAreaActionsMixin(PromptTextAreaEditActionsMixin):
    """PromptTextArea action handlers and prompt-bar integration."""

    if TYPE_CHECKING:
        _vcs_mru_index: int | None

        def _clear_snippet_session(self) -> None: ...
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
        self._clear_snippet_session()
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
        self._clear_snippet_session()
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
        if bar._stack.selected_item.is_auxiliary_pane:
            return
        if self.document.line_count != 1:
            return

        self._clear_insert_g_prefix()
        self._clear_snippet_session()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None

        PromptInputBar = prompt_bar_class()
        bar.post_message(
            PromptInputBar.HistoryRequested(
                preserve_prompt_bar=True,
                origin_bar=bar,
                origin_text_area=cast("PromptTextArea", self),
                origin_pane_id=self.id or "",
                prompt_seed=self.text,
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
        if bar._mode == "prompt" and bar._stack.selected_item.is_auxiliary_pane:
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
        """Open the prompt submit chooser for plain ``<enter>``."""
        from sase.ace.tui.modals.prompt_submit_choice_modal import (
            PromptSubmitChoice,
            PromptSubmitChoiceModal,
        )

        bar = self._find_prompt_bar()
        if (
            bar is None
            or bar._mode != "prompt"
            or bar._stack.selected_item.is_auxiliary_pane
        ):
            return

        prompt_texts = bar.all_prompt_texts()
        prompt_count = sum(1 for text in prompt_texts if text.strip())
        if prompt_count <= 0:
            return
        target = bar.xprompt_target()
        origin = self._capture_submit_choice_origin(bar)

        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()

        def _on_result(result: PromptSubmitChoice | None) -> None:
            self._refocus_if_needed()
            if result is not None and not self._submit_choice_origin_is_current(origin):
                self._notify_submit_choice_stale()
                self._refocus_submit_choice_origin(origin)
                return
            if result == "send":
                self.action_submit_prompt()
            elif result == "all":
                self.action_submit_prompt_stack()
            elif result == "current":
                self.action_submit_prompt()
            elif result == "write":
                bar.request_write_xprompt()
            elif result == "save_as":
                bar.request_save_as_xprompt()

        self.app.push_screen(
            PromptSubmitChoiceModal(
                prompt_count=prompt_count,
                pane_count=len(prompt_texts),
                target=target,
                is_dirty=bool(target is not None and bar._stack.is_dirty),
            ),
            _on_result,
        )

    @staticmethod
    def _capture_submit_choice_origin(bar: Any) -> _SubmitChoiceOrigin:
        """Snapshot the prompt-bar state represented by the submit chooser."""
        bar._sync_state_from_widgets()
        stack = bar._stack
        return _SubmitChoiceOrigin(
            bar=bar,
            stack=stack,
            mode=bar._mode,
            generation=bar._generation,
            selected_index=stack.selected_index,
            selected_item_id=stack.selected_item.item_id,
            frontmatter=stack.frontmatter,
            binding=stack.binding,
            readonly_target=getattr(bar, "_readonly_xprompt_target", None),
            target_generation=getattr(bar, "_xprompt_target_generation", 0),
            panes=tuple(
                _SubmitChoicePaneOrigin(
                    item_id=item.item_id,
                    text=item.text,
                    role=item.role,
                )
                for item in stack.items
            ),
        )

    @staticmethod
    def _submit_choice_origin_is_current(origin: _SubmitChoiceOrigin) -> bool:
        """Return whether the chooser still describes the mounted draft."""
        bar = origin.bar
        if (
            not bar.is_mounted
            or bar._stack is not origin.stack
            or bar._mode != origin.mode
            or bar._generation != origin.generation
            or bar._stack.selected_index != origin.selected_index
            or bar._stack.selected_item.item_id != origin.selected_item_id
            or bar._stack.frontmatter != origin.frontmatter
            or bar._stack.binding is not origin.binding
            or getattr(bar, "_readonly_xprompt_target", None)
            is not origin.readonly_target
            or getattr(bar, "_xprompt_target_generation", 0) != origin.target_generation
        ):
            return False
        panes = tuple(
            _SubmitChoicePaneOrigin(
                item_id=item.item_id,
                text=item.text,
                role=item.role,
            )
            for item in bar._stack.items
        )
        return panes == origin.panes

    def _refocus_submit_choice_origin(self, origin: _SubmitChoiceOrigin) -> None:
        """Return focus to the current draft after a stale chooser closes."""
        try:
            if origin.bar.is_mounted:
                origin.bar.active_text_area().focus()
        except Exception:
            pass

    def _notify_submit_choice_stale(self) -> None:
        """Tell the user a stale submit chooser was ignored."""
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify(
                "Prompt changed while confirmation was open. Review it and submit again.",
                severity="warning",
                title="Prompt not launched",
                markup=False,
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
        self._clear_snippet_session()

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
