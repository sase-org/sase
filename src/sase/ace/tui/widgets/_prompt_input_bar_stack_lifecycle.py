"""Focus, change handling, and sizing for ``PromptInputBar`` stacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.dom import NoScreen
from textual.widgets import TextArea

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
else:
    _MixinBase = object

# Inactive panes never grow past this many content rows so the active pane keeps
# the room. Phase 2 height rule: active grows most, inactive compact.
_INACTIVE_PANE_MAX_ROWS = 4


class PromptInputBarStackLifecycleMixin(_MixinBase):
    """Prompt stack focus, text-change, and height lifecycle."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_visible: bool
        _g_prefix_hints_line_count: int
        _g_prefix_hints_visible: bool
        _search_command_line_count: int
        _search_command_visible: bool
        _stack: PromptStackState
        _title_mode_suffix: str

        def _apply_active_classes(self) -> None: ...
        def _clear_active_completion_state(self) -> None: ...
        def _frontmatter_panel_reserved_rows(
            self, height_cap: int | None = None
        ) -> int: ...
        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...
        def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None: ...
        def _update_todo_count_for_text_area(self, text_area: object) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def refresh_cursor_readouts(self) -> None: ...
        def show_jinja_diagnostics(self, diagnostics: object) -> None: ...

    def focus_item(self, index: int) -> int:
        """Focus the pane at *index* (clamped); return the clamped index."""
        self._clear_active_completion_state()
        self._stack.focus(index)
        self._apply_active_classes()
        self.active_text_area().focus()
        self._refresh_title()
        self.refresh_frontmatter_panel_from_stack()
        self._schedule_height_update()
        return self._stack.selected_index

    def _sync_state_from_widgets(self) -> None:
        """Copy each mounted pane's live editor state back into the stack model."""
        for item in self._stack.items:
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            item.text = text_area.text
            row, column = text_area.cursor_location
            item.cursor = (row, column)
            item.mode = text_area._vim_mode

    def on_descendant_focus(self, event: object) -> None:
        """Track the active pane when focus moves between panes."""
        self._schedule_xprompt_stale_check()
        widget = getattr(event, "widget", None)
        if widget is None or len(self._stack) <= 1:
            return
        for index, item in enumerate(self._stack.items):
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            if text_area is widget and index != self._stack.selected_index:
                self._clear_active_completion_state()
                self._stack.selected_index = index
                self._apply_active_classes()
                self.refresh_frontmatter_panel_from_stack()
                self._schedule_height_update()
                return

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes.

        Purely passive: a typed ``---`` is left as literal text in the pane.  The
        properties panel and extra panes are reached only through explicit
        prompt NORMAL-mode ``g=`` and ``g-`` controls.
        """
        text_area = event.text_area
        if not isinstance(text_area, PromptTextArea):
            text_area = self.active_text_area()
        text_area.show_line_numbers = text_area.document.line_count > 1
        text_area._on_prompt_completion_context_changed()
        self._sync_state_from_widgets()
        self._update_todo_count_for_text_area(text_area)
        self._refresh_title(self._title_mode_suffix)
        self._schedule_height_update()
        self.refresh_cursor_readouts()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Refresh soft completion and the cursor readout when the cursor moves."""
        if isinstance(event.text_area, PromptTextArea):
            event.text_area._on_prompt_completion_context_changed()
        self.refresh_cursor_readouts()

    def _maybe_show_active_jinja_diagnostics(self) -> None:
        """Restore active Jinja diagnostics after a higher-priority panel hides."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        diagnostics = getattr(text_area, "_jinja_diagnostics", None)
        if diagnostics is None:
            return
        has_jinja = bool(getattr(diagnostics, "has_jinja", False))
        ok = bool(getattr(diagnostics, "ok", True))
        unknown = tuple(getattr(diagnostics, "unknown_variables", ()) or ())
        if has_jinja and (not ok or unknown):
            self.show_jinja_diagnostics(diagnostics)

    @staticmethod
    def _text_area_visual_rows(text_area: PromptTextArea) -> int:
        """Count *text_area*'s rendered rows using Textual's wrapped document."""
        wrapped_document = getattr(text_area, "wrapped_document", None)
        wrapped_height = getattr(wrapped_document, "height", None)
        if isinstance(wrapped_height, int) and wrapped_height > 0:
            return wrapped_height
        return max(1, text_area.document.line_count)

    def _get_visual_line_count(self) -> int:
        """Count rendered text rows of the active pane."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return 1
        return self._text_area_visual_rows(text_area)

    def _update_height(self) -> None:
        """Auto-grow the bar based on content, up to the full screen height."""
        if not self.is_mounted:
            return
        try:
            screen_height = self.screen.size.height
        except NoScreen:
            return
        max_height = screen_height - 2
        completion_rows = self._completion_line_count if self._completion_visible else 0
        g_prefix_rows = (
            self._g_prefix_hints_line_count if self._g_prefix_hints_visible else 0
        )
        search_rows = (
            self._search_command_line_count if self._search_command_visible else 0
        )
        frontmatter_cap = max(
            0,
            max_height - 3 - completion_rows - g_prefix_rows - search_rows,
        )
        frontmatter_rows = min(
            self._frontmatter_panel_reserved_rows(frontmatter_cap),
            frontmatter_cap,
        )
        panel_rows = completion_rows + frontmatter_rows + g_prefix_rows + search_rows
        if len(self._stack) <= 1:
            # Single pane: identical formula to the pre-stack bar. +2 for the
            # bar's top/bottom border, plus transient panels when visible.
            visual_lines = self._get_visual_line_count()
            new_height = min(
                max(visual_lines + 2 + panel_rows, 3),
                max_height,
            )
            self.styles.height = new_height
            return
        self._apply_multi_pane_heights(max_height, panel_rows)

    def _apply_multi_pane_heights(self, max_height: int, completion_rows: int) -> None:
        """Size each pane so the stack fits the screen, active pane growing most.

        Inactive panes compact to at most ``_INACTIVE_PANE_MAX_ROWS`` rows first;
        the active pane takes whatever budget remains.  If the panes still
        cannot fit, inactive panes shrink toward one row before the active pane
        does.
        """
        items = self._stack.items
        try:
            panes = [
                self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
                for item in items
            ]
        except Exception:
            return
        count = len(panes)
        active = self._stack.selected_index
        # Reserve: bar border (2) + completion panel + one separator row/pane.
        reserve = 2 + completion_rows + count
        content_budget = max(count, max_height - reserve)

        desired = [max(1, self._text_area_visual_rows(pane)) for pane in panes]
        alloc = [
            1
            if index == active
            else max(1, min(desired[index], _INACTIVE_PANE_MAX_ROWS))
            for index in range(count)
        ]
        inactive_used = sum(alloc) - alloc[active]
        alloc[active] = max(1, min(desired[active], content_budget - inactive_used))

        overflow = sum(alloc) - content_budget
        if overflow > 0:
            for index in range(count):
                if overflow <= 0:
                    break
                if index == active:
                    continue
                take = min(alloc[index] - 1, overflow)
                alloc[index] -= take
                overflow -= take
            if overflow > 0:
                alloc[active] -= min(alloc[active] - 1, overflow)

        for pane, height in zip(panes, alloc, strict=True):
            pane.styles.height = height
        bar_height = min(reserve + sum(alloc), max_height)
        self.styles.height = max(bar_height, 3)
        self._scroll_active_pane_visible()

    def _scroll_active_pane_visible(self) -> None:
        """Keep the focused pane reachable if the stack overflows vertically."""
        try:
            self.active_text_area().scroll_visible(animate=False)
        except Exception:
            pass

    def _schedule_height_update(self) -> None:
        """Update now and once more after Textual has refreshed wrapping."""
        self._update_height()
        self.call_after_refresh(self._update_height)

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._schedule_height_update()
        self.refresh_cursor_readouts()
