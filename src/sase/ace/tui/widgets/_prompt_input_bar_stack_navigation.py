"""Prompt stack pane navigation and mutation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.xprompt import extract_vcs_workflow_tag

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarStackNavigationMixin(_MixinBase):
    """Prompt stack focus, reorder, and transient-state cleanup actions."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _apply_active_classes(self) -> None: ...
        def _rebuild_stack(
            self,
            enter_mode: str | None = None,
            *,
            restore_focus: PromptFocusRestore | None = None,
        ) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def hide_file_completions(self) -> None: ...
        def hide_soft_completion(self) -> None: ...

    def focus_relative(self, delta: int, target_mode: str = "normal") -> bool:
        """Move pane focus by *delta* (the ``gk`` / ``gj`` keymaps).

        ``gk`` focuses the previous/higher pane (``delta`` ``-1``) and ``gj`` the
        next/lower pane (``delta`` ``+1``); focus cycles at the stack edges, so
        ``gk`` from the top pane wraps to the bottom and ``gj`` from the bottom
        wraps to the top.  Navigation is a pure focus change; no pane is
        rebuilt, so each pane keeps its cursor and edit state.  ``target_mode``
        in; normal ``g`` callers pass ``"normal"`` and insert ``Ctrl+G``
        callers pass ``"insert"``.  Returns ``True`` when the selection moved.
        """
        if len(self._stack) <= 1:
            return False
        self._clear_active_completion_state()
        if not self._stack.move_focus(delta):
            return False
        self._apply_active_classes()
        text_area = self.active_text_area()
        text_area.focus()
        if target_mode == "insert":
            text_area._enter_insert_mode()
        else:
            text_area._enter_normal_mode()
        self._schedule_height_update()
        return True

    def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool:
        """Reorder the active pane by *delta* (the ``gK`` / ``gJ`` keymaps).

        ``delta`` of ``-1`` moves the pane higher/earlier (``gK``) and ``+1``
        lower/later (``gJ``); reorder cycles at the stack edges, so ``gK`` from
        the top pane wraps it to the bottom and ``gJ`` from the bottom wraps it
        to the top.  The live pane texts are synced into the model first so the
        rebuild preserves what the user has typed; the moved pane stays active
        and lands in *target_mode* ("normal" or "insert").  Normal ``g`` callers
        pass ``"normal"`` and insert ``Ctrl+G`` callers pass ``"insert"``.
        Returns ``True`` when it moved.
        """
        if len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        if not self._stack.move_selected(delta):
            return False
        self._rebuild_stack(enter_mode=target_mode)
        return True

    def add_bottom_pane(self) -> None:
        """Append a new bottom pane and drop into it (the ``g-`` keymap).

        Only meaningful in prompt mode; feedback / approve-prompt bars are not
        multi-agent surfaces, so it is a no-op elsewhere.  The new pane is
        focused in insert mode so the user can immediately type the next agent
        prompt, pushing the previous panes up.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        self._stack.append_bottom(self._added_bottom_pane_initial_text())
        self._rebuild_stack(enter_mode="insert")

    def _added_bottom_pane_initial_text(self) -> str:
        """Return the VCS workflow seed for a newly appended agent pane."""
        selected = self._stack.selected_item
        if selected.is_auxiliary_pane:
            return ""
        vcs_tag = extract_vcs_workflow_tag(f"{selected.text} ")
        if vcs_tag is None:
            return ""
        return f"{vcs_tag.strip()} "

    def _clear_active_completion_state(self) -> None:
        """Drop transient active-pane state before stack focus/mutation."""
        try:
            text_area = self.active_text_area()
        except Exception:
            text_area = None
        if text_area is not None:
            text_area._clear_insert_g_prefix()
            text_area._clear_normal_g_prefix()
            text_area._clear_file_completion()
            text_area._clear_soft_completion(cancel_timer=True)
            text_area._clear_xprompt_arg_hint()
            text_area._clear_prompt_search(clear_highlights=True)
        self.hide_file_completions()
        self.hide_soft_completion()
