"""Prompt stack widget construction and stack-aware API for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical
from textual.widget import Widget

from sase.ace.tui.widgets._prompt_cursor_readout import (
    cursor_readout_position,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_lifecycle import (
    PromptInputBarStackLifecycleMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets._prompt_input_bar_stack_separator import (
    MiniXPromptSeparatorInfo,
    PromptStackSeparator,
    SnippetSeparatorInfo,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_xprompt import (
    PromptInputBarStackXPromptMixin,
)
from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    split_prompt_text,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptInputBarStackRenderingMixin(
    PromptInputBarStackXPromptMixin,
    PromptInputBarStackLifecycleMixin,
):
    """Prompt stack model, rendering, focus, and height helpers."""

    if TYPE_CHECKING:
        _generation: int
        _mode: str
        _placeholder: str
        _stack: PromptStackState
        _subtitle_base: str

        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _render_subtitle(self, base: str) -> Text: ...
        def _sync_todo_counts_from_mounted_panes(self) -> None: ...
        def _sync_todo_counts_from_stack(self) -> None: ...

    # -- stack model + rendering ---------------------------------------------

    def _state_from_text(self, text: str) -> PromptStackState:
        """Build stack state from *text*, splitting only real multi-prompts.

        Feedback / approve-prompt modes are never multi-agent surfaces, so they
        stay single-pane.  In prompt mode the canonical parser decides: text
        with real ``---`` separators (outside fences/frontmatter) splits into
        panes; anything else stays a single pane.  A leading YAML frontmatter
        block is lifted onto the stack in prompt mode so the structured panel
        and launch payload share the same source of truth.
        """
        if self._mode in ("feedback", "approve_prompt"):
            return PromptStackState.single(text)
        if len(split_prompt_text(text)) > 1:
            return PromptStackState.from_text(text)
        return PromptStackState.single(text, lift_frontmatter=True)

    def _pane_id(self, item: PromptStackItem) -> str:
        """Stable, generation-scoped widget id for *item*'s text area."""
        return f"prompt-input-g{self._generation}-{item.item_id}"

    def _sep_id(self, item: PromptStackItem) -> str:
        """Stable, generation-scoped widget id for *item*'s separator row."""
        return f"prompt-sep-g{self._generation}-{item.item_id}"

    def _build_pane_widgets(self) -> list[Widget]:
        """Build the separator + text-area widgets for the current stack."""
        widgets: list[Widget] = []
        multi = len(self._stack) > 1
        agent_number = 0
        for index, item in enumerate(self._stack.items):
            if item.is_snippet_pane:
                label = "snippet"
            elif item.is_mini_xprompt_pane:
                label = "mini xprompt"
            else:
                agent_number += 1
                label = f"agent {agent_number}"
            if multi:
                active = index == self._stack.selected_index
                state = "active" if active else "inactive"
                classes = f"prompt-stack-separator {state}"
                snippet_info = None
                mini_xprompt_info = None
                if item.is_snippet_pane:
                    classes += " snippet"
                    snippet_info = self._snippet_separator_info(item)
                    if snippet_info.state == "dirty":
                        classes += " snippet-dirty"
                elif item.is_mini_xprompt_pane:
                    classes += " mini-xprompt"
                    mini_xprompt_info = self._mini_xprompt_separator_info(item)
                    if mini_xprompt_info.state in {"dirty", "stale"}:
                        classes += " mini-xprompt-dirty"
                widgets.append(
                    PromptStackSeparator(
                        label,
                        active=active,
                        snippet=snippet_info,
                        mini_xprompt=mini_xprompt_info,
                        id=self._sep_id(item),
                        classes=classes,
                    )
                )
            widgets.append(
                PromptTextArea(
                    item.text,
                    language="markdown",
                    soft_wrap=True,
                    show_line_numbers=item.text.count("\n") > 0,
                    highlight_cursor_line=False,
                    id=self._pane_id(item),
                    placeholder=self._placeholder,
                    classes=self._pane_classes(index, multi),
                )
            )
        return widgets

    def _pane_classes(self, index: int, multi: bool) -> str:
        """Return the CSS classes for the pane at *index*."""
        if not multi:
            return "prompt-input solo"
        state = "active" if index == self._stack.selected_index else "inactive"
        classes = f"prompt-input prompt-pane {state}"
        if self._stack.items[index].is_snippet_pane:
            classes += " snippet-target"
        elif self._stack.items[index].is_mini_xprompt_pane:
            classes += " mini-xprompt-target"
        return classes

    def _snippet_separator_info(self, item: PromptStackItem) -> SnippetSeparatorInfo:
        """Return the chip/destination/marker state for the snippet pane's rule."""
        target = item.snippet_target
        assert target is not None
        if not target.exists:
            state = "new"
        elif self._stack.snippet_is_dirty:
            state = "dirty"
        else:
            state = "clean"
        return SnippetSeparatorInfo(
            trigger=target.trigger,
            destination=target.display_path,
            state=state,
        )

    def _mini_xprompt_separator_info(
        self, item: PromptStackItem
    ) -> MiniXPromptSeparatorInfo:
        """Return the chip/destination/marker state for the mini-xprompt rule."""
        target = item.mini_xprompt_target
        assert target is not None
        if not target.exists:
            state = "new"
        elif self._stack.mini_xprompt_is_dirty:
            state = "dirty"
        elif target.changed_on_disk:
            state = "stale"
        else:
            state = "clean"
        return MiniXPromptSeparatorInfo(
            name=target.name,
            destination=target.display_path,
            state=state,
        )

    def _rebuild_stack(
        self,
        enter_mode: str | None = None,
        *,
        restore_focus: PromptFocusRestore | None = None,
    ) -> None:
        """Re-render the prompt stack to match ``self._stack`` from scratch.

        Used by deliberate whole-stack replacements
        (``load_stack_from_xprompt_markdown``), the inline history load
        (``load_prompt_into_pane``), and the structural keymaps (reorder, add
        pane).  Bumps the generation so freshly mounted panes never share ids
        with the panes still being detached asynchronously.  *enter_mode*
        optionally puts the rebuilt
        active pane into vim ``"normal"`` or ``"insert"`` mode once it has
        mounted, so reorder keeps the user in normal mode while adding a pane
        drops them into the new pane ready to type.
        """
        self._generation += 1
        self._sync_todo_counts_from_stack()
        self._refresh_title()
        try:
            container = self.query_one("#prompt-stack", Vertical)
        except Exception:
            return
        container.remove_children()
        container.mount(*self._build_pane_widgets())
        self.call_after_refresh(lambda: self._after_rebuild(enter_mode, restore_focus))

    def _after_rebuild(
        self,
        enter_mode: str | None = None,
        restore_focus: PromptFocusRestore | None = None,
    ) -> None:
        """Focus + style the active pane once a rebuilt stack has mounted."""
        if restore_focus is not None:
            self._stack.focus(self._restore_focus_index(restore_focus.item_id))
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        text_area.focus()
        restored_cursor: tuple[int, int] | None = None
        if restore_focus is None:
            self._cursor_to_end(text_area)
        else:
            restored_cursor = self._clamp_cursor_location(
                text_area,
                restore_focus.cursor,
            )
            text_area.cursor_location = restored_cursor
        text_area._warm_current_xprompt_assist_entries()
        text_area._warm_current_artifact_ref_completion_catalog()
        text_area._warm_vcs_project_completion_catalog()
        text_area._warm_model_completion_catalog()
        text_area._warm_prompt_path_inventory()
        text_area._warm_history_word_completion_cache()
        text_area._warm_common_placeholder_cache()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self._sync_todo_counts_from_mounted_panes()
        self._refresh_title()
        if restore_focus is not None:
            if restore_focus.vim_mode == "insert":
                text_area._enter_insert_mode()
            else:
                text_area._enter_normal_mode()
            if restored_cursor is not None:
                text_area.cursor_location = restored_cursor
        elif enter_mode == "normal":
            text_area._enter_normal_mode()
        elif enter_mode == "insert":
            text_area._enter_insert_mode()
        self._schedule_height_update()

    def _restore_focus_index(self, item_id: str) -> int:
        """Return the restored item index, falling back to the bottom agent pane."""
        for index, item in enumerate(self._stack.items):
            if item.item_id == item_id:
                return index
        for index in range(len(self._stack.items) - 1, -1, -1):
            if not self._stack.items[index].is_auxiliary_pane:
                return index
        return self._stack.selected_index

    @staticmethod
    def _clamp_cursor_location(
        text_area: PromptTextArea,
        cursor: tuple[int, int],
    ) -> tuple[int, int]:
        """Clamp a stored ``(row, column)`` to *text_area*'s current document."""
        row, column = cursor
        doc = text_area.document
        row = max(0, min(row, doc.line_count - 1))
        line = doc.get_line(row)
        column = max(0, min(column, len(line)))
        return row, column

    @staticmethod
    def _cursor_to_end(text_area: PromptTextArea) -> None:
        """Move *text_area*'s cursor to the end of its document."""
        if not text_area.text:
            return
        doc = text_area.document
        last_line = doc.line_count - 1
        text_area.cursor_location = (last_line, len(doc.get_line(last_line)))

    def _apply_active_classes(self) -> None:
        """Sync each pane/separator's active/inactive class with the selection."""
        multi = len(self._stack) > 1
        for index, item in enumerate(self._stack.items):
            active = index == self._stack.selected_index
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            text_area.set_class(active, "active")
            text_area.set_class(not active, "inactive")
            if not multi:
                continue
            try:
                separator = self.query_one(
                    f"#{self._sep_id(item)}", PromptStackSeparator
                )
            except Exception:
                continue
            separator.set_class(active, "active")
            separator.set_class(not active, "inactive")
            separator.set_active(active)
        self.refresh_cursor_readouts()

    def _snippet_frame_state(self) -> str | None:
        """Return ``"safe"``/``"dirty"`` while an auxiliary pane holds focus.

        ``None`` off an auxiliary pane: the bar frame answers "what does
        ``<enter>`` do right now", so it tracks focus, not mere existence.
        """
        if self._mode != "prompt":
            return None
        item = self._stack.selected_item
        if item.is_snippet_pane and item.snippet_target is not None:
            return (
                "dirty"
                if self._snippet_separator_info(item).state == "dirty"
                else "safe"
            )
        if item.is_mini_xprompt_pane and item.mini_xprompt_target is not None:
            state = self._mini_xprompt_separator_info(item).state
            return "dirty" if state in {"dirty", "stale"} else "safe"
        return None

    def _refresh_snippet_frame_classes(self) -> None:
        """Sync bar-level auxiliary frame classes with the active pane."""
        state = self._snippet_frame_state()
        self.set_class(state is not None, "snippet-mode")
        self.set_class(state == "safe", "snippet-safe")
        self.set_class(state == "dirty", "snippet-dirty")
        item = self._stack.selected_item
        mini = state is not None and item.is_mini_xprompt_pane
        self.set_class(mini, "mini-xprompt-mode")
        self.set_class(mini and state == "safe", "mini-xprompt-safe")
        self.set_class(mini and state == "dirty", "mini-xprompt-dirty")

    def refresh_cursor_readouts(self) -> None:
        """Sync the active pane's subtitle readout and each parked separator's rule.

        A cursor readout paints immediately on the UI thread, like a
        highlight move -- never debounced.  Every pane lookup is guarded
        since the bar is routinely asked to refresh while panes are
        mid-mount or mid-detach.
        """
        self._refresh_snippet_frame_classes()
        self.border_subtitle = self._render_subtitle(self._subtitle_base)
        if len(self._stack) <= 1:
            return
        for index, item in enumerate(self._stack.items):
            try:
                separator = self.query_one(
                    f"#{self._sep_id(item)}", PromptStackSeparator
                )
            except Exception:
                continue
            if item.is_snippet_pane:
                snippet_info = self._snippet_separator_info(item)
                separator.set_snippet_info(snippet_info)
                separator.set_class(snippet_info.state == "dirty", "snippet-dirty")
            elif item.is_mini_xprompt_pane:
                mini_info = self._mini_xprompt_separator_info(item)
                separator.set_mini_xprompt_info(mini_info)
                separator.set_class(
                    mini_info.state in {"dirty", "stale"},
                    "mini-xprompt-dirty",
                )
            if index == self._stack.selected_index:
                separator.set_position(None)
                continue
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            line, column = cursor_readout_position(text_area)
            separator.set_position((line, column), text_area._vim_mode)

    # -- stack-aware public API ----------------------------------------------

    def active_text_area(self) -> PromptTextArea:
        """Return the ``PromptTextArea`` for the currently active pane."""
        item = self._stack.selected_item
        return self.query_one(f"#{self._pane_id(item)}", PromptTextArea)

    def active_text(self) -> str:
        """Return the active pane's text verbatim."""
        return self.active_text_area().text

    def is_multi_pane(self) -> bool:
        """Return ``True`` when the bar holds more than one prompt pane.

        Used by the prompt text area to decide whether the normal-mode pane
        controls move panes: ``K``/``J`` focus and ``Up``/``Down`` reorder act
        only on a real multi-pane stack.  A single-pane bar has no pane to focus
        or reorder, so it swallows bare ``K``/``J`` as a no-op (keeping them off
        the app-level Agents-tab bindings) and leaves ``Up``/``Down`` for
        normal-mode cursor movement.
        """
        return len(self._stack) > 1

    def all_prompt_texts(self) -> list[str]:
        """Return every agent pane's live text, top-to-bottom launch order."""
        self._sync_state_from_widgets()
        return list(self._stack.agent_texts)

    def current_prompt_text(self) -> str:
        """Return the whole stack joined into one canonical multi-prompt string.

        Mirrors the whole-stack submit contract: empty panes are dropped and
        non-empty panes are joined with ``\\n---\\n`` (re-attaching
        frontmatter).  A single pane without frontmatter remains just that
        pane's stripped text.
        """
        self._sync_state_from_widgets()
        return self._stack.join()

    def is_stacked(self) -> bool:
        """True when the bar currently holds more than one agent prompt pane."""
        return self._stack.agent_count > 1

    def xprompt_markdown_for_editor(self) -> str:
        """Return the whole stack as spaced xprompt markdown for the all-pane editor.

        Syncs the live panes into the model first, then renders them in launch
        order with blank-line-padded ``---`` segment separators
        (``\\n\\n---\\n\\n``), re-attaching the canonical frontmatter followed by
        a blank line only when properties are set (so an empty frontmatter
        leaves no stray ``---\\n---`` block).  This editor-friendly spacing is
        scoped to the buffer multi-pane ``^G`` opens; the launch payload from
        :meth:`current_prompt_text` keeps the compact ``\\n---\\n`` form.  The
        edited result is reloaded via :meth:`load_stack_from_xprompt_markdown`,
        whose splitter drops the surrounding blank segments.  Leading
        frontmatter lives on the stack and is re-attached here, not kept inside
        a body pane.
        """
        self._sync_state_from_widgets()
        return self._stack.editor_markdown()
