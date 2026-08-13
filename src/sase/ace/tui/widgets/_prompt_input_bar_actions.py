"""Submission, cancellation, and snippet behavior for PromptInputBar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets._todo_highlight import todo_annotation_count
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_suffix_skeleton,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
else:
    _MixinBase = object


@dataclass(frozen=True, slots=True)
class _PreparedPane:
    """One live pane captured before a possibly delayed submission."""

    item_id: str
    pane_id: str
    text: str
    text_area: PromptTextArea


@dataclass(frozen=True, slots=True)
class _PreparedSubmission:
    """Exact prompt-bar state and payload awaiting an optional confirmation."""

    shape: Literal["whole_bar", "selected_pane", "whole_stack", "drop_empty"]
    value: str
    mode: str
    keep_bar: bool
    whole_stack: bool
    todo_count: int
    stack: PromptStackState
    generation: int
    selected_index: int
    selected_item_id: str
    frontmatter: str
    binding: object | None
    panes: tuple[_PreparedPane, ...]
    origin_text_area: PromptTextArea


def _end_location_after_insert(
    start: tuple[int, int],
    inserted: str,
) -> tuple[int, int]:
    """Return the document location at the end of *inserted* placed at *start*.

    Mirrors ``EditResult.end_location`` for an insertion that begins at *start*,
    so the cursor can be positioned at the end of an inline expansion without
    relying on the keyboard-replace return value.
    """
    lines = inserted.split("\n")
    if len(lines) == 1:
        return (start[0], start[1] + len(lines[0]))
    return (start[0] + len(lines) - 1, len(lines[-1]))


class PromptInputBarActionsMixin(_MixinBase):
    """Prompt submit/cancel actions and snippet insertion helpers."""

    if TYPE_CHECKING:
        Cancelled: Any
        Submitted: Any
        _generation: int
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
        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _confirm_discard_dirty_snippet(
            self,
            proceed: Callable[[], None],
        ) -> bool: ...
        def close_snippet_target(
            self,
            reason: Literal["saved", "discarded", "replaced"],
        ) -> bool: ...
        def request_save_snippet_target_pane(
            self,
            origin_text_area: PromptTextArea | None = None,
        ) -> None: ...

    def _handle_text_submission(
        self,
        _text: str,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Process a selected-pane submission from a pane's TextArea.

        In a single-pane bar (or feedback / approve-prompt mode, which are never
        stacks) this is the pre-stack contract — the whole bar is submitted and
        the app unmounts it.  In a multi-pane stack this is the ``g<enter>`` /
        chooser-current path: the selected pane is launched while the bar stays
        mounted (``keep_bar``) so the remaining panes can be submitted in turn;
        an empty selected pane is simply dropped instead of launched.
        """
        if self._text_submission_needs_dirty_snippet_guard(origin_text_area):
            self._confirm_discard_dirty_snippet(
                lambda: self._handle_text_submission_after_snippet_guard(
                    origin_text_area
                )
            )
            return
        self._handle_text_submission_after_snippet_guard(origin_text_area)

    def _handle_text_submission_after_snippet_guard(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Process a text submission after any snippet discard guard has passed."""
        prepared = self._prepare_text_submission(origin_text_area)
        if prepared is not None:
            self._confirm_or_commit_submission(prepared)

    def _text_submission_needs_dirty_snippet_guard(
        self,
        origin_text_area: PromptTextArea | None,
    ) -> bool:
        """Return whether the selected-pane submit would discard a dirty snippet."""
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if (
            not self._stack.snippet_is_dirty
            or self._stack.selected_item.is_snippet_pane
        ):
            return False
        if self._stack.agent_count > 1:
            return False
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return False
        return (origin_text_area.id or "") == self._pane_id(self._stack.selected_item)

    def _prepare_text_submission(
        self,
        origin_text_area: PromptTextArea | None,
    ) -> _PreparedSubmission | None:
        """Capture a whole-bar or selected-pane submit before any mutation."""
        self._sync_state_from_widgets()
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return None

        if self._mode == "prompt" and self._stack.selected_item.is_snippet_pane:
            self.request_save_snippet_target_pane(origin_text_area)
            return None

        if self._mode != "prompt" or self._stack.agent_count <= 1:
            return self._snapshot_submission(
                shape="whole_bar",
                value=self._stack.join(),
                keep_bar=False,
                whole_stack=False,
                todo_count=(
                    todo_annotation_count(self._stack.selected_item.text)
                    if self._mode == "prompt"
                    else 0
                ),
                origin_text_area=origin_text_area,
            )

        selected_text = self._stack.selected_item.text.strip()
        return self._snapshot_submission(
            shape="selected_pane" if selected_text else "drop_empty",
            value=(
                self._stack.attach_frontmatter(selected_text) if selected_text else ""
            ),
            keep_bar=bool(selected_text),
            whole_stack=False,
            todo_count=(
                todo_annotation_count(self._stack.selected_item.text)
                if selected_text
                else 0
            ),
            origin_text_area=origin_text_area,
        )

    def _handle_whole_stack_submission(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Submit the whole stack as one multi-prompt via the submit chooser.

        Only meaningful in prompt mode — feedback / approve-prompt bars are not
        multi-agent surfaces — so it is a no-op elsewhere.  The non-empty panes
        are joined with ``\\n---\\n`` and handed to the app, which unmounts the
        bar and routes the joined text through the existing multi-prompt /
        xprompt swarm launch rules.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if self._stack.snippet_is_dirty:
            self._confirm_discard_dirty_snippet(
                lambda: self._handle_whole_stack_submission_after_snippet_guard(
                    origin_text_area
                )
            )
            return
        self._handle_whole_stack_submission_after_snippet_guard(origin_text_area)

    def _handle_whole_stack_submission_after_snippet_guard(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Submit the whole stack after the snippet-discard guard has passed."""
        self._sync_state_from_widgets()
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return
        prepared = self._snapshot_submission(
            shape="whole_stack",
            value=self._stack.join(),
            keep_bar=False,
            whole_stack=True,
            todo_count=sum(
                todo_annotation_count(item.text)
                for item in self._stack.agent_items
                if item.text.strip()
            ),
            origin_text_area=origin_text_area,
        )
        if prepared is not None:
            self._confirm_or_commit_submission(prepared)

    def _snapshot_submission(
        self,
        *,
        shape: Literal["whole_bar", "selected_pane", "whole_stack", "drop_empty"],
        value: str,
        keep_bar: bool,
        whole_stack: bool,
        todo_count: int,
        origin_text_area: PromptTextArea,
    ) -> _PreparedSubmission | None:
        """Capture the exact mounted stack that produced a submission action."""
        panes: list[_PreparedPane] = []
        for item in self._stack.items:
            pane_id = self._pane_id(item)
            try:
                text_area = self.query_one(f"#{pane_id}", PromptTextArea)
            except Exception:
                return None
            panes.append(
                _PreparedPane(
                    item_id=item.item_id,
                    pane_id=pane_id,
                    text=text_area.text,
                    text_area=text_area,
                )
            )

        origin = next(
            (pane for pane in panes if pane.text_area is origin_text_area),
            None,
        )
        if origin is None or origin.item_id != self._stack.selected_item.item_id:
            return None

        return _PreparedSubmission(
            shape=shape,
            value=value,
            mode=self._mode,
            keep_bar=keep_bar,
            whole_stack=whole_stack,
            todo_count=todo_count,
            stack=self._stack,
            generation=self._generation,
            selected_index=self._stack.selected_index,
            selected_item_id=self._stack.selected_item.item_id,
            frontmatter=self._stack.frontmatter,
            binding=self._stack.binding,
            panes=tuple(panes),
            origin_text_area=origin_text_area,
        )

    def _confirm_or_commit_submission(
        self,
        prepared: _PreparedSubmission,
    ) -> None:
        """Warn for visible prompt TODOs, otherwise commit immediately."""
        if prepared.mode != "prompt" or prepared.todo_count <= 0:
            self._commit_prepared_submission(prepared)
            return

        from sase.ace.tui.modals import ConfirmActionModal, ConfirmKind

        noun = "marker" if prepared.todo_count == 1 else "markers"
        handled = False

        def _on_result(confirmed: bool | None) -> None:
            nonlocal handled
            if handled:
                return
            handled = True
            if confirmed is True:
                self._commit_prepared_submission(prepared)
            else:
                self._refocus_prepared_origin(prepared)

        self.app.push_screen(
            ConfirmActionModal(
                "Launch prompt with TODOs?",
                (
                    f"This submission contains {prepared.todo_count} visible "
                    f"TODO {noun}. Launch it anyway?"
                ),
                kind=ConfirmKind.NEUTRAL,
                confirm_label="Launch",
                cancel_label="Keep editing",
                default="cancel",
            ),
            _on_result,
        )

    def _prepared_submission_is_current(
        self,
        prepared: _PreparedSubmission,
    ) -> bool:
        """Return whether *prepared* still describes this exact mounted bar."""
        if (
            not self.is_mounted
            or self._stack is not prepared.stack
            or self._generation != prepared.generation
            or self._stack.selected_index != prepared.selected_index
            or self._stack.selected_item.item_id != prepared.selected_item_id
            or self._stack.frontmatter != prepared.frontmatter
            or self._stack.binding is not prepared.binding
            or tuple(item.item_id for item in self._stack.items)
            != tuple(pane.item_id for pane in prepared.panes)
        ):
            return False

        for item, pane in zip(self._stack.items, prepared.panes, strict=True):
            if item.text != pane.text:
                return False
            text_area = self._resolve_pane_target(pane.text_area, pane.pane_id)
            if text_area is None or text_area.text != pane.text:
                return False
        return True

    def _commit_prepared_submission(
        self,
        prepared: _PreparedSubmission,
    ) -> None:
        """Commit one validated submission without re-entering confirmation."""
        if not self._prepared_submission_is_current(prepared):
            return

        if prepared.shape in ("selected_pane", "drop_empty"):
            self._stack.remove_selected()
            self._clear_active_completion_state()
            if prepared.shape == "selected_pane":
                self.post_message(
                    self.Submitted(
                        prepared.value,
                        mode=prepared.mode,
                        keep_bar=prepared.keep_bar,
                    )
                )
            self._rebuild_stack(enter_mode="insert")
            return

        self.post_message(
            self.Submitted(
                prepared.value,
                mode=prepared.mode,
                keep_bar=prepared.keep_bar,
                whole_stack=prepared.whole_stack,
            )
        )

    def _refocus_prepared_origin(self, prepared: _PreparedSubmission) -> None:
        """Return focus to the unchanged pane that opened confirmation."""
        origin = next(
            (
                pane
                for pane in prepared.panes
                if pane.text_area is prepared.origin_text_area
            ),
            None,
        )
        if origin is None:
            return
        try:
            text_area = self._resolve_pane_target(origin.text_area, origin.pane_id)
            if text_area is not None:
                text_area.focus()
        except Exception:
            pass

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

                if self._stack.has_snippet_pane:
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

    def insert_snippet(
        self,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> None:
        """Insert a snippet reference at the active pane's cursor.

        Legacy entry point that targets whichever pane is active *now*. The
        ``#@`` selector path routes through :meth:`insert_snippet_at_target`
        instead so it can act on the exact pane that opened the modal.

        The '#' from the '#@' trigger is already in the input
        ('@' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
            entry: Optional selected xprompt metadata for smart argument insertion.
        """
        self._insert_snippet_into(self.active_text_area(), snippet_name, entry)

    def insert_snippet_at_target(
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: tuple[tuple[int, int], tuple[int, int]] | None,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> bool:
        """Insert a snippet into the pane that opened the ``#@`` selector.

        Targets the captured origin pane rather than the currently active one,
        so a multi-pane stack inserts into the upper pane the trigger was typed
        in even if focus moved while the modal was open.

        Returns ``False`` without mutating any pane when the captured target is
        stale -- the originating pane or bar was unmounted/rebuilt while the
        modal was open -- so the caller can notify and leave every prompt
        unchanged. Insertion lands on the empty suffix range right after the
        literal ``#`` of *trigger_range*, preserving the ``Enter`` contract of
        inserting ``#name`` after the trigger ``#``.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False
        if trigger_range is not None:
            # Collapse the selection onto the empty range just after the trigger
            # '#' so only that suffix is replaced and the '#' itself is kept.
            text_area.cursor_location = trigger_range[1]
        self._insert_snippet_into(text_area, snippet_name, entry)
        return True

    def expand_xprompt_at_target(
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: tuple[tuple[int, int], tuple[int, int]] | None,
        expanded_text: str,
    ) -> bool:
        """Inline-expand a selected xprompt into the pane that opened ``#@``.

        Unlike :meth:`insert_snippet_at_target` -- which keeps the trigger ``#``
        and inserts a ``#name`` reference after it -- this *consumes* the ``#``,
        replacing the whole captured *trigger_range* with the already-rendered
        *expanded_text*. The replacement goes through the captured pane's
        ``_replace_via_keyboard()`` so it is recorded as one undoable
        ``TextArea`` edit: a multi-character range replace lands in its own
        isolated undo batch, so a single prompt NORMAL-mode ``u`` restores the
        exact pre-expansion text, including the literal ``#`` trigger.

        Targets the captured origin pane rather than whichever pane is active
        when the modal closes (matching ``insert_snippet_at_target``), and
        returns ``False`` without mutating anything when that target is stale --
        the originating pane or bar was unmounted/rebuilt while the modal was
        open -- so the caller can notify and leave every prompt unchanged.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False
        if text_area.read_only:
            # ``_replace_via_keyboard`` is a no-op in read-only (NORMAL) mode.
            # ``#@`` only fires from INSERT mode, so this is defensive; never
            # report success on a no-op edit (the caller would dismiss the
            # selector for nothing).
            return False

        # Drop transient completion / soft-completion / xprompt-arg-hint state on
        # the captured target before the edit: the ``#`` is about to disappear, so
        # any menu or hint anchored to it would otherwise linger over the spliced
        # body.
        text_area._clear_insert_g_prefix()
        text_area._clear_file_completion()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()

        start, end = trigger_range if trigger_range is not None else text_area.selection
        text_area._replace_via_keyboard(expanded_text, start, end)
        # The replacement inserts ``expanded_text`` starting at ``start``; place
        # the cursor at its end. (Mirrors ``EditResult.end_location`` without
        # relying on the keyboard-replace return value, matching the snippet
        # insertion path.)
        text_area.cursor_location = _end_location_after_insert(start, expanded_text)
        text_area.focus()
        return True

    def _resolve_pane_target(
        self,
        target_text_area: object,
        pane_id: str,
    ) -> PromptTextArea | None:
        """Return the captured origin pane if still live in this bar, else ``None``.

        A prompt-stack rebuild remounts panes under a fresh generation-scoped id
        (see :meth:`_pane_id`), so a captured *pane_id* that still resolves to
        the very same widget instance is proof the origin pane survived;
        a missing id, a mismatched instance, or an unmounted bar means the
        target is stale and the operation must be skipped.

        Shared by the ``#@`` selector (snippet insertion / inline expansion) and
        the ``Ctrl+I`` history load, which all act on the exact pane that opened
        their modal rather than whatever pane is active when it closes.  An empty
        *pane_id* falls back to *target_text_area* itself when it is still
        mounted, letting a programmatic caller without a captured id target the
        pane it passed directly.
        """
        if not self.is_mounted or not isinstance(target_text_area, PromptTextArea):
            return None
        if pane_id:
            try:
                found = self.query_one(f"#{pane_id}", PromptTextArea)
            except Exception:
                return None
            return found if found is target_text_area else None
        return target_text_area if target_text_area.is_mounted else None

    def _insert_snippet_into(
        self,
        text_area: PromptTextArea,
        snippet_name: str,
        entry: XPromptAssistEntry | None,
    ) -> None:
        """Insert *snippet_name* (and optional smart args) into *text_area*."""
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
        # End-of-line required-text insertions get the ``:: `` shorthand; inline
        # ones keep ``::`` so existing following text is the single delimiter.
        line = text_area.document.get_line(end[0])
        append_text_arg_space = end[1] == len(line)
        next_char = line[end[1]] if end[1] < len(line) else None
        skeleton = xprompt_completion_suffix_skeleton(
            entry,
            append_text_arg_space=append_text_arg_space,
            next_char=next_char,
        )
        if not text_area._expand_snippet_template_at_range(
            skeleton,
            start,
            end,
            session_policy="nest",
        ):
            return False

        text_area._note_xprompt_completion_spacer(entry)
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
