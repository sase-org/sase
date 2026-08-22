"""Prompt submission preparation and confirmation actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets._todo_highlight import todo_annotation_count
from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

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


class PromptInputBarSubmissionActionsMixin(_MixinBase):
    """Prepare, confirm, and commit prompt submissions."""

    if TYPE_CHECKING:
        Submitted: Any
        _generation: int
        _mode: str
        _stack: PromptStackState

        def active_text_area(self) -> PromptTextArea: ...
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
        def request_save_mini_xprompt_target_pane(
            self,
            origin_text_area: PromptTextArea | None = None,
        ) -> None: ...
        def request_save_snippet_target_pane(
            self,
            origin_text_area: PromptTextArea | None = None,
        ) -> None: ...
        def _resolve_pane_target(
            self,
            target_text_area: object,
            pane_id: str,
        ) -> PromptTextArea | None: ...

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
            not self._stack.auxiliary_is_dirty
            or self._stack.selected_item.is_auxiliary_pane
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
        if self._mode == "prompt" and self._stack.selected_item.is_mini_xprompt_pane:
            self.request_save_mini_xprompt_target_pane(origin_text_area)
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
        if self._stack.auxiliary_is_dirty:
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
