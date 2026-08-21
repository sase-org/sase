"""Prompt stack widget construction and stack-aware API for ``PromptInputBar``."""

from __future__ import annotations

from dataclasses import dataclass
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
from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
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


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
    """Return a prefix/suffix of *value* that fits in *width* terminal cells."""
    if width <= 0:
        return ""
    chars = reversed(value) if from_right else iter(value)
    used = 0
    taken: list[str] = []
    for char in chars:
        char_width = max(cell_len(char), 0)
        if used + char_width > width:
            break
        taken.append(char)
        used += char_width
    if from_right:
        taken.reverse()
    return "".join(taken)


def _middle_elide_cells(value: str, width: int) -> str:
    """Fit *value* in *width* cells, preserving the path tail."""
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


@dataclass(frozen=True)
class _SnippetSeparatorInfo:
    """The chip/destination/state data the snippet pane's separator renders."""

    trigger: str
    destination: str
    state: str  # "clean" | "dirty" | "new"


@dataclass(frozen=True)
class _MiniXPromptSeparatorInfo:
    """The chip/destination/state data the mini-xprompt separator renders."""

    name: str
    destination: str
    state: str  # "clean" | "dirty" | "new" | "stale"


class _PromptStackSeparator(Static):
    """Width-aware separator row for one prompt-stack pane."""

    def __init__(
        self,
        label: str,
        *,
        active: bool = False,
        snippet: _SnippetSeparatorInfo | None = None,
        mini_xprompt: _MiniXPromptSeparatorInfo | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__("", **kwargs)
        self.label = label
        self.active = active
        self.snippet = snippet
        self.mini_xprompt = mini_xprompt
        self.position: tuple[int, int] | None = None
        self.vim_mode: str = "insert"

    def set_active(self, active: bool) -> None:
        """Update active state and refresh the rendered rule when it changes."""
        if self.active == active:
            return
        self.active = active
        self.refresh()

    def set_snippet_info(self, info: _SnippetSeparatorInfo | None) -> None:
        """Replace the snippet chip/destination/marker, no-op when unchanged."""
        if self.snippet == info:
            return
        self.snippet = info
        self.refresh()

    def set_mini_xprompt_info(self, info: _MiniXPromptSeparatorInfo | None) -> None:
        """Replace the mini-xprompt chip/destination/marker when changed."""
        if self.mini_xprompt == info:
            return
        self.mini_xprompt = info
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
        """Render a centered pane label connected by full-width hairline rules."""
        width = max(0, int(self.size.width))
        if self.snippet is not None:
            return self._render_snippet(width)
        if self.mini_xprompt is not None:
            return self._render_mini_xprompt(width)

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

    def _theme_color(self, attr: str, fallback: str) -> str:
        """Return a theme color by attribute name, falling back outside an app."""
        try:
            theme = self.app.current_theme
        except Exception:
            return fallback
        color = getattr(theme, attr, None)
        return str(color) if color else fallback

    def _snippet_marker(self) -> tuple[str, str]:
        """Return ``(text, style)`` for the snippet pane's state marker."""
        info = self.snippet
        assert info is not None
        if info.state == "new":
            return "new", f"bold {self._theme_color('success', 'green')}"
        if info.state == "dirty":
            return "●", f"bold {self._theme_color('warning', 'yellow')}"
        return "✓", "dim"

    def _mini_xprompt_marker(self) -> tuple[str, str]:
        """Return ``(text, style)`` for the mini-xprompt pane's state marker."""
        info = self.mini_xprompt
        assert info is not None
        if info.state == "new":
            return "new", f"bold {self._theme_color('success', 'green')}"
        if info.state == "dirty":
            return "●", f"bold {self._theme_color('warning', 'yellow')}"
        if info.state == "stale":
            return (
                "⚠ changed on disk",
                f"bold {self._theme_color('warning', 'yellow')}",
            )
        return "✓", "dim"

    def _render_snippet(self, width: int) -> Text:
        """Render the trigger-labeled title bar for the pinned snippet pane.

        Unlike the centered agent label, this row reads left-to-right: the
        ``⇥ <trigger>`` chip, the destination file (dim, middle-elided so a
        deep path never overruns the rule), then a truthful state marker.
        """
        info = self.snippet
        assert info is not None
        chip_prefix = f"{_STACK_SEPARATOR_ACTIVE_MARKER} " if self.active else ""
        chip = f"{chip_prefix}⇥ {info.trigger}"
        chip_style = "bold" if self.active else "dim"
        marker_text, marker_style = self._snippet_marker()

        fixed_width = cell_len(f"  {chip}   {marker_text}  ")
        dest_budget = max(0, width - fixed_width)
        destination = (
            _middle_elide_cells(info.destination, dest_budget)
            if info.destination and dest_budget > 0
            else ""
        )

        body = Text(no_wrap=True, overflow="crop")
        body.append(" ")
        body.append(chip, style=chip_style)
        if destination:
            body.append(" · ", style="dim")
            body.append(destination, style="dim")
        body.append(" ")
        body.append(marker_text, style=marker_style)
        body.append(" ")
        label_width = body.cell_len

        if width <= label_width:
            text = body.copy()
            text.no_wrap = True
            text.overflow = "ellipsis"
            text.truncate(width, overflow="ellipsis")
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append_text(body)
        text.append_text(self._render_right_rule(right_width))
        return text

    def _render_mini_xprompt(self, width: int) -> Text:
        """Render the name-labeled title bar for a pinned mini-xprompt pane."""
        info = self.mini_xprompt
        assert info is not None
        chip_prefix = f"{_STACK_SEPARATOR_ACTIVE_MARKER} " if self.active else ""
        chip = f"{chip_prefix}#{info.name}"
        chip_style = "bold" if self.active else "dim"
        marker_text, marker_style = self._mini_xprompt_marker()

        fixed_width = cell_len(f"  {chip}   {marker_text}  ")
        dest_budget = max(0, width - fixed_width)
        destination = (
            _middle_elide_cells(info.destination, dest_budget)
            if info.destination and dest_budget > 0
            else ""
        )

        body = Text(no_wrap=True, overflow="crop")
        body.append(" ")
        body.append(chip, style=chip_style)
        if destination:
            body.append(" · ", style="dim")
            body.append(destination, style="dim")
        body.append(" ")
        body.append(marker_text, style=marker_style)
        body.append(" ")
        label_width = body.cell_len

        if width <= label_width:
            text = body.copy()
            text.no_wrap = True
            text.overflow = "ellipsis"
            text.truncate(width, overflow="ellipsis")
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append_text(body)
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
                    _PromptStackSeparator(
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

    def _snippet_separator_info(self, item: PromptStackItem) -> _SnippetSeparatorInfo:
        """Return the chip/destination/marker state for the snippet pane's rule."""
        target = item.snippet_target
        assert target is not None
        if not target.exists:
            state = "new"
        elif self._stack.snippet_is_dirty:
            state = "dirty"
        else:
            state = "clean"
        return _SnippetSeparatorInfo(
            trigger=target.trigger,
            destination=target.display_path,
            state=state,
        )

    def _mini_xprompt_separator_info(
        self, item: PromptStackItem
    ) -> _MiniXPromptSeparatorInfo:
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
        return _MiniXPromptSeparatorInfo(
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
                    f"#{self._sep_id(item)}", _PromptStackSeparator
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
                    f"#{self._sep_id(item)}", _PromptStackSeparator
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
