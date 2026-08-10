"""Prompt stack widget construction and stack-aware API for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_cursor_readout import (
    cursor_readout_cell_width,
    cursor_readout_position,
    format_cursor_readout,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_lifecycle import (
    PromptInputBarStackLifecycleMixin,
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

_STACK_SEPARATOR_RULE = "─"
_STACK_SEPARATOR_ACTIVE_MARKER = "▍"


class _PromptStackSeparator(Static):
    """Width-aware separator row for one prompt-stack pane."""

    def __init__(self, label: str, *, active: bool = False, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.label = label
        self.active = active
        self.position: tuple[int, int] | None = None
        self.vim_mode: str = "insert"

    def set_active(self, active: bool) -> None:
        """Update active state and refresh the rendered rule when it changes."""
        if self.active == active:
            return
        self.active = active
        self.refresh()

    def set_position(
        self, position: tuple[int, int] | None, vim_mode: str = "insert"
    ) -> None:
        """Update the parked-pane cursor readout, no-op when nothing changed."""
        if self.position == position and self.vim_mode == vim_mode:
            return
        self.position = position
        self.vim_mode = vim_mode
        self.refresh()

    def render(self) -> Text:
        """Render a centered agent label connected by full-width hairline rules."""
        width = max(0, int(self.size.width))
        label = self.label
        if self.active:
            label = f"{_STACK_SEPARATOR_ACTIVE_MARKER} {label}"
        padded_label = f" {label} "
        label_width = cell_len(padded_label)
        label_style = "bold" if self.active else "dim"

        if width <= label_width:
            text = Text(padded_label.strip(), no_wrap=True, overflow="ellipsis")
            text.truncate(width, overflow="ellipsis")
            text.stylize(label_style)
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append(padded_label, style=label_style)
        text.append_text(self._render_right_rule(right_width))
        return text

    def _render_right_rule(self, right_width: int) -> Text:
        """Return the right-hand rule run, carrying the readout when it fits.

        The centered-label math above never changes: this only decides how
        the *already allotted* right-hand rule cells are spent.  When the
        readout does not fit alongside at least one rule cell on each side,
        it is omitted entirely -- never abbreviated to a second format.
        """
        if self.position is not None:
            line, column = self.position
            chip_cells = cursor_readout_cell_width(line, column) + 2
            if right_width >= chip_cells + 2:
                dash_count = right_width - chip_cells - 1
                text = Text(no_wrap=True, overflow="crop")
                text.append(_STACK_SEPARATOR_RULE * dash_count, style="dim")
                text.append(" ")
                text.append_text(
                    format_cursor_readout(line, column, vim_mode=self.vim_mode)
                )
                text.append(" ")
                text.append(_STACK_SEPARATOR_RULE, style="dim")
                return text
        return Text(_STACK_SEPARATOR_RULE * right_width, style="dim")


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
            else:
                agent_number += 1
                label = f"agent {agent_number}"
            if multi:
                active = index == self._stack.selected_index
                state = "active" if active else "inactive"
                widgets.append(
                    _PromptStackSeparator(
                        label,
                        active=active,
                        id=self._sep_id(item),
                        classes=f"prompt-stack-separator {state}",
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
        return f"prompt-input prompt-pane {state}"

    def _rebuild_stack(self, enter_mode: str | None = None) -> None:
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
        self.call_after_refresh(lambda: self._after_rebuild(enter_mode))

    def _after_rebuild(self, enter_mode: str | None = None) -> None:
        """Focus + style the active pane once a rebuilt stack has mounted."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        text_area.focus()
        self._cursor_to_end(text_area)
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
        if enter_mode == "normal":
            text_area._enter_normal_mode()
        elif enter_mode == "insert":
            text_area._enter_insert_mode()
        self._schedule_height_update()

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
                    f"#{self._sep_id(item)}", _PromptStackSeparator
                )
            except Exception:
                continue
            separator.set_class(active, "active")
            separator.set_class(not active, "inactive")
            separator.set_active(active)
        self.refresh_cursor_readouts()

    def refresh_cursor_readouts(self) -> None:
        """Sync the active pane's subtitle readout and each parked separator's rule.

        A cursor readout paints immediately on the UI thread, like a
        highlight move -- never debounced.  Every pane lookup is guarded
        since the bar is routinely asked to refresh while panes are
        mid-mount or mid-detach.
        """
        self.border_subtitle = self._render_subtitle(self._subtitle_base)
        if len(self._stack) <= 1:
            return
        for index, item in enumerate(self._stack.items):
            try:
                separator = self.query_one(
                    f"#{self._sep_id(item)}", _PromptStackSeparator
                )
            except Exception:
                continue
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
