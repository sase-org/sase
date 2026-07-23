"""PromptTextArea actions, mode transitions, and focus helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.screen import ModalScreen

from sase.ace.tui.widgets._jinja_pair_editing import (
    plan_jinja_delete_left,
    plan_jinja_delete_right,
)
from sase.ace.tui.widgets._paired_text_editing import (
    plan_pair_delete_left,
    plan_pair_delete_right,
)
from sase.ace.tui.widgets._prompt_bullet_editing import (
    normalize_prompt_bullet_replay_text,
    prompt_bullet_sibling_prefix,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

if TYPE_CHECKING:
    from sase.ace.tui.widgets.vim_text_area import VimTextArea as _MixinBase

    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
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
        _pending_visual_surround_range: (
            tuple[str, tuple[int, int], tuple[int, int], int] | None
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

    def _normal_open_below_insert_text(self, row: int) -> str:
        """Auto-continue a containing prompt hyphen bullet for ``o``."""
        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        return f"\n{prefix}" if prefix is not None else "\n"

    def _normal_open_above_insert_text(self, row: int) -> str:
        """Auto-continue a containing prompt hyphen bullet for ``O``."""
        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        return f"{prefix}\n" if prefix is not None else "\n"

    def _normalize_normal_open_below_replay_text(self, insert_text: str) -> str:
        """Avoid replaying a typed marker after structural prompt bullet text."""
        row = self.cursor_location[0]
        return normalize_prompt_bullet_replay_text(
            self.document.get_line(row),
            insert_text,
        )

    def _normalize_normal_open_above_replay_text(self, insert_text: str) -> str:
        """Avoid replaying a typed marker after structural prompt bullet text."""
        row = self.cursor_location[0]
        return normalize_prompt_bullet_replay_text(
            self.document.get_line(row),
            insert_text,
        )

    def _notify_host_text_undo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode undo changed this pane's text.

        Lets the bar unstage xprompt inputs an inline expansion auto-staged when
        (and only when) this undo reversed that expansion's body splice. A pane
        with no parent bar -- or an undo that matches no expansion transaction --
        is a no-op. Overrides :class:`VimTextArea`'s no-op host hook.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_undo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _notify_host_text_redo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode redo changed this pane's text."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_redo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        """Route the vim mode + pending indicator to the parent ``PromptInputBar``.

        Overrides :class:`VimTextArea`'s border-based default. Reproduces the
        prompt bar's per-mode chrome: NORMAL shows the stack-aware
        ``normal_mode_subtitle`` plus any pending indicator; VISUAL / V-LINE show
        the selection hints; INSERT shows the (title-suffix-free)
        ``insert_mode_subtitle``. A pane with no parent bar is a no-op.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        mode = self._vim_mode
        if mode in ("visual", "visual_line"):
            title = "[V-LINE]" if mode == "visual_line" else "[VISUAL]"
            bar._refresh_title(title)
            subtitle = "[Esc] normal  [o] swap ends  [^C] cancel"
            if indicator:
                subtitle += f"  {indicator}"
        elif mode == "insert":
            bar._refresh_title()
            subtitle = bar.insert_mode_subtitle()
        else:
            bar._refresh_title("[NORMAL]")
            # Derive the base from the bar so a stacked prompt keeps advertising
            # its stack keymaps while a count/operator/``g`` prefix is pending.
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

    def _dispatch_host_g_prefix_key(self, key: str) -> bool:
        """Forward a pending ``g<key>`` to the parent bar's stack dispatcher."""
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            return bool(dispatch(key))
        return False

    def _show_pending_g_hints(self) -> None:
        """Reveal the parent bar's vim ``g``-prefix continuation hint panel."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show()

    def _hide_pending_g_hints(self) -> None:
        """Hide the parent bar's vim ``g``-prefix continuation hint panel."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()

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
        """Submit the whole prompt stack as one multi-prompt via the chooser."""
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
                origin_bar=bar,
                origin_text_area=cast("PromptTextArea", self),
                origin_pane_id=self.id or "",
            )
        )

    def action_insert_newline(self) -> None:
        """Insert a newline, continuing a containing prompt hyphen bullet."""
        row = self.cursor_location[0]
        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        insert = f"\n{prefix}" if prefix is not None else "\n"
        start, end = self.selection
        self._replace_via_keyboard(insert, start, end)

    def _refresh_completion_after_cursor_move(self) -> None:
        """Refresh prompt assist surfaces after TextArea cursor actions."""
        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()

    def action_cursor_left(self, select: bool = False) -> None:
        super().action_cursor_left(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_right(self, select: bool = False) -> None:
        super().action_cursor_right(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_up(self, select: bool = False) -> None:
        super().action_cursor_up(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_down(self, select: bool = False) -> None:
        super().action_cursor_down(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_line_start(self, select: bool = False) -> None:
        super().action_cursor_line_start(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_line_end(self, select: bool = False) -> None:
        super().action_cursor_line_end(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_word_left(self, select: bool = False) -> None:
        super().action_cursor_word_left(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_word_right(self, select: bool = False) -> None:
        super().action_cursor_word_right(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_page_up(self) -> None:
        super().action_cursor_page_up()
        self._refresh_completion_after_cursor_move()

    def action_cursor_page_down(self) -> None:
        super().action_cursor_page_down()
        self._refresh_completion_after_cursor_move()

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
