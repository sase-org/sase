"""Prompt search command-line panel for ``PromptInputBar``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.search_command_line import render_search_command_line

if TYPE_CHECKING:
    from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True)
class _PromptSearchPaneSnapshot:
    """One mounted prompt pane and its matches in stack order."""

    stack_index: int
    text_area: PromptTextArea
    spans: tuple[SearchSpan, ...]


@dataclass(frozen=True)
class _PromptSearchDestination:
    """A globally resolved match plus whole-stack wrap state."""

    pane: _PromptSearchPaneSnapshot
    local_match_index: int
    wrapped: bool


class PromptInputBarSearchMixin(_MixinBase):
    """Transient Vim-style search command line for the prompt body."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_panel_kind: str | None
        _completion_visible: bool
        _stack: PromptStackState
        _search_command_line_count: int
        _search_command_visible: bool

        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _schedule_height_update(self) -> None: ...
        def _frontmatter_panel(self) -> FrontmatterPanel | None: ...
        def focus_item(self, index: int) -> int: ...
        def hide_soft_completion(self) -> None: ...
        def hide_g_prefix_hints(self) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prompt_search_register: tuple[str, SearchDirection] | None = None
        super().__init__(*args, **kwargs)

    def record_prompt_search(
        self,
        query: str,
        direction: SearchDirection,
    ) -> None:
        """Record the last successful search shared by this bar's panes."""
        self._prompt_search_register = (query, direction)

    def prompt_search_register(self) -> tuple[str, SearchDirection] | None:
        """Return the last successful search shared by this bar's panes."""
        return self._prompt_search_register

    def repeat_prompt_search(
        self,
        origin: PromptTextArea,
        *,
        reverse: bool = False,
        count: int = 1,
    ) -> bool:
        """Repeat the shared search through every mounted pane in stack order."""
        search_register = self._prompt_search_register
        if search_register is None:
            origin._show_prompt_search_feedback("no previous search")
            return True

        query, recorded_direction = search_register
        direction = (
            self._invert_search_direction(recorded_direction)
            if reverse
            else recorded_direction
        )
        panes = self._prompt_search_pane_snapshot(query)
        destination = self._resolve_prompt_search_destination(
            panes,
            origin,
            direction,
            count=max(1, count),
        )
        if destination is None:
            for pane in panes:
                pane.text_area._clear_prompt_search_result()
            origin._show_prompt_search_feedback("pattern not found")
            return True

        target = destination.pane.text_area
        origin._clear_prompt_search_result()
        if target is not origin:
            self.focus_item(destination.pane.stack_index)
            target._enter_normal_mode()

        selection = SearchSelection(
            index=destination.local_match_index,
            wrapped=destination.wrapped,
        )
        target._apply_prompt_search_result(destination.pane.spans, selection)
        if target is not origin:
            target.scroll_cursor_visible()
            self._schedule_height_update()
        if destination.wrapped:
            origin._show_prompt_search_feedback(self._wrap_feedback_message(direction))
        return True

    def _prompt_search_pane_snapshot(
        self,
        query: str,
    ) -> tuple[_PromptSearchPaneSnapshot, ...]:
        """Capture mounted panes and literal smartcase matches in stack order."""
        panes: list[_PromptSearchPaneSnapshot] = []
        for stack_index, item in enumerate(self._stack.items):
            try:
                text_area = self.query_one(
                    f"#{self._pane_id(item)}",
                    PromptTextArea,
                )
            except Exception:
                continue
            panes.append(
                _PromptSearchPaneSnapshot(
                    stack_index=stack_index,
                    text_area=text_area,
                    spans=find_search_matches(text_area.text, query),
                )
            )
        return tuple(panes)

    @staticmethod
    def _resolve_prompt_search_destination(
        panes: tuple[_PromptSearchPaneSnapshot, ...],
        origin: PromptTextArea,
        direction: SearchDirection,
        *,
        count: int,
    ) -> _PromptSearchDestination | None:
        """Resolve a counted repeat against the whole ordered pane snapshot."""
        origin_pane = next(
            (pane for pane in panes if pane.text_area is origin),
            None,
        )
        if origin_pane is None:
            return None

        candidates = [
            (pane, local_index, span)
            for pane in panes
            for local_index, span in enumerate(pane.spans)
        ]
        if not candidates:
            return None

        origin_offset = origin._absolute_offset(origin.cursor_location)
        if direction == "forward":
            base_index = next(
                (
                    index
                    for index, (pane, _local_index, (start, _end)) in enumerate(
                        candidates
                    )
                    if pane.stack_index > origin_pane.stack_index
                    or (
                        pane.stack_index == origin_pane.stack_index
                        and start > origin_offset
                    )
                ),
                0,
            )
            initially_wrapped = not any(
                pane.stack_index > origin_pane.stack_index
                or (
                    pane.stack_index == origin_pane.stack_index
                    and start > origin_offset
                )
                for pane, _local_index, (start, _end) in candidates
            )
            steps = count - 1
            destination_index = (base_index + steps) % len(candidates)
            wrapped = initially_wrapped or base_index + steps >= len(candidates)
        else:
            reverse_base = next(
                (
                    index
                    for index in range(len(candidates) - 1, -1, -1)
                    if candidates[index][0].stack_index < origin_pane.stack_index
                    or (
                        candidates[index][0].stack_index == origin_pane.stack_index
                        and candidates[index][2][0] < origin_offset
                    )
                ),
                len(candidates) - 1,
            )
            initially_wrapped = not any(
                pane.stack_index < origin_pane.stack_index
                or (
                    pane.stack_index == origin_pane.stack_index
                    and start < origin_offset
                )
                for pane, _local_index, (start, _end) in candidates
            )
            steps = count - 1
            destination_index = (reverse_base - steps) % len(candidates)
            wrapped = initially_wrapped or reverse_base - steps < 0

        pane, local_match_index, _span = candidates[destination_index]
        return _PromptSearchDestination(
            pane=pane,
            local_match_index=local_match_index,
            wrapped=wrapped,
        )

    @staticmethod
    def _invert_search_direction(direction: SearchDirection) -> SearchDirection:
        """Return the opposite search direction."""
        return "reverse" if direction == "forward" else "forward"

    @staticmethod
    def _wrap_feedback_message(direction: SearchDirection) -> str:
        """Return Vim-style whole-stack wrap feedback for *direction*."""
        if direction == "forward":
            return "search hit BOTTOM, continuing at TOP"
        return "search hit TOP, continuing at BOTTOM"

    def prepare_search_command_line(self) -> None:
        """Hide other transient prompt panels before search opens."""
        self._hide_completion_panel_for_search()
        try:
            self.hide_g_prefix_hints()
        except Exception:
            pass
        frontmatter = None
        try:
            frontmatter = self._frontmatter_panel()
        except Exception:
            pass
        if frontmatter is not None and not frontmatter.has_class("hidden"):
            frontmatter.add_class("hidden")
            self._schedule_height_update()

    def _hide_completion_panel_for_search(self) -> None:
        """Hide completion/Jinja panels without restoring diagnostics."""
        try:
            self.hide_soft_completion()
        except Exception:
            pass
        try:
            panel = self.query_one("#prompt-completion", Static)
        except Exception:
            return
        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_panel_kind = None
        self._completion_line_count = 0
        self._schedule_height_update()

    def show_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        current_index: int | None,
        total: int,
    ) -> None:
        """Render and reveal the search command line."""
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        panel.border_title = "search"
        panel.border_subtitle = "[enter] accept  [esc/^c] cancel"
        panel.update(
            self._render_search_command_line(
                direction=direction,
                query=query,
                current_index=current_index,
                total=total,
            )
        )
        panel.remove_class("hidden")

        was_visible = self._search_command_visible
        old_line_count = self._search_command_line_count
        self._search_command_visible = True
        self._search_command_line_count = 4
        if not was_visible or old_line_count != self._search_command_line_count:
            self._schedule_height_update()

    def hide_search_command_line(self) -> None:
        """Hide the search command line."""
        if not self._search_command_visible:
            return
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.add_class("hidden")
        self._search_command_visible = False
        self._search_command_line_count = 0
        self._schedule_height_update()

    def _render_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        current_index: int | None,
        total: int,
    ) -> Text:
        width = max(0, int(getattr(self.size, "width", 0)) - 4)
        return render_search_command_line(
            direction=direction,
            query=query,
            current_index=current_index,
            total=total,
            width=width,
        )
