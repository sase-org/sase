"""Interactive Vim-style search state for ``PromptTextArea``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
    select_search_match,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptSearchMixin(_MixinBase):
    """Interactive incremental search for prompt NORMAL mode."""

    if TYPE_CHECKING:
        _count_prefix: str
        _file_completion_active: bool
        _pending_change_surround_locations: (
            tuple[
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
            ]
            | None
        )
        _pending_count: int | None
        _pending_keys: str
        _pending_operator: str
        _pending_operator_count: int
        _pending_surround_range: tuple[str, tuple[int, int], tuple[int, int]] | None

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _clear_insert_g_prefix(self) -> None: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_search_highlights(self, *, refresh: bool = True) -> None: ...
        def _clear_soft_completion(
            self,
            *,
            cancel_timer: bool = False,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _find_prompt_bar(self) -> Any: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _set_search_highlights(
            self,
            spans: tuple[SearchSpan, ...],
            current_index: int | None = None,
            *,
            refresh: bool = True,
        ) -> None: ...
        def _update_count_display(self) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._search_active = False
        self._search_query = ""
        self._search_direction: SearchDirection = "forward"
        self._search_origin_cursor: tuple[int, int] = (0, 0)
        self._search_origin_offset = 0
        self._search_current_selection: SearchSelection | None = None
        super().__init__(*args, **kwargs)

    def _is_prompt_search_active(self) -> bool:
        """Return whether the prompt search command line owns key input."""
        return self._search_active

    def _start_prompt_search(self, direction: SearchDirection) -> None:
        """Open incremental search from the current cursor location."""
        self._clear_insert_g_prefix()
        self._search_active = True
        self._search_direction = direction
        self._search_query = ""
        self._search_origin_cursor = self.cursor_location
        self._search_origin_offset = self._absolute_offset(self.cursor_location)
        self._search_current_selection = None

        self._pending_keys = ""
        self._pending_count = None
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self._count_prefix = ""

        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()
        self._clear_search_highlights()

        bar = self._find_prompt_bar()
        if bar is not None:
            prepare = getattr(bar, "prepare_search_command_line", None)
            if callable(prepare):
                prepare()
        self._render_prompt_search_command_line()

    def _handle_prompt_search_key(self, event: Key) -> bool:
        """Handle a key while the search command line is active."""
        if not self._search_active:
            return False

        if event.key in {"escape", "ctrl+c"}:
            self._cancel_prompt_search()
            return True
        if event.key == "enter":
            self._confirm_prompt_search()
            return True
        if event.key in {"backspace", "ctrl+h"}:
            if self._search_query:
                self._search_query = self._search_query[:-1]
                self._update_prompt_search_preview()
            return True

        char = event.character
        if char is not None and len(char) == 1 and event.key != "tab":
            self._search_query += char
            self._update_prompt_search_preview()
            return True

        return True

    def _update_prompt_search_preview(self) -> None:
        """Recompute matches, move the preview cursor, and refresh highlights."""
        query = self._search_query
        if not query:
            self.cursor_location = self._search_origin_cursor
            self._search_current_selection = None
            self._clear_search_highlights()
            self._render_prompt_search_command_line()
            return

        spans = find_search_matches(self.text, query)
        selection = select_search_match(
            spans,
            self._search_origin_offset,
            self._search_direction,
            include_origin=True,
        )
        self._search_current_selection = selection
        if selection is None:
            self.cursor_location = self._search_origin_cursor
            self._set_search_highlights(spans)
        else:
            self._apply_prompt_search_result(spans, selection)

        self._render_prompt_search_command_line()

    def _confirm_prompt_search(self) -> None:
        """Close search, keeping the preview cursor and recording the query."""
        if self._search_query and self._search_current_selection is not None:
            bar = self._find_prompt_bar()
            record = (
                getattr(bar, "record_prompt_search", None) if bar is not None else None
            )
            if callable(record):
                record(self._search_query, self._search_direction)
        self._search_active = False
        self._hide_prompt_search_command_line()
        self._update_count_display()

    def _cancel_prompt_search(self) -> None:
        """Close search, restoring the cursor and clearing highlights."""
        self.cursor_location = self._search_origin_cursor
        self._search_active = False
        self._search_query = ""
        self._search_current_selection = None
        self._clear_search_highlights()
        self._hide_prompt_search_command_line()
        self._update_count_display()

    def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None:
        """Tear down any active command line, optionally clearing highlights."""
        if self._search_active:
            self._search_active = False
            self._search_query = ""
            self._search_current_selection = None
            self._hide_prompt_search_command_line()
        if clear_highlights:
            self._clear_search_highlights()

    def _render_prompt_search_command_line(self) -> None:
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_search_command_line", None)
        if not callable(show):
            return
        selection = self._search_current_selection
        show(
            direction=self._search_direction,
            query=self._search_query,
            current_index=selection.index if selection is not None else None,
            total=len(getattr(self, "_search_match_spans", ())),
        )

    def _hide_prompt_search_command_line(self) -> None:
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_search_command_line", None)
        if callable(hide):
            hide()

    def _replace_via_keyboard(
        self,
        insert: str,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> Any:
        """Clear transient search highlights after a keyboard edit."""
        result = super()._replace_via_keyboard(insert, start, end)
        if result is not None:
            self._clear_prompt_search(clear_highlights=True)
        return result

    def delete(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        maintain_selection_offset: bool = True,
    ) -> Any:
        """Clear transient search highlights after a direct text deletion."""
        result = super().delete(
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )
        self._clear_prompt_search(clear_highlights=True)
        return result

    def _repeat_prompt_search(
        self,
        *,
        reverse: bool = False,
        count: int = 1,
    ) -> bool:
        """Delegate a repeat of the shared search register to the prompt bar."""
        bar = self._find_prompt_bar()
        repeat = getattr(bar, "repeat_prompt_search", None) if bar is not None else None
        if callable(repeat):
            return bool(repeat(self, reverse=reverse, count=count))
        self._show_prompt_search_feedback("no previous search")
        return True

    def _apply_prompt_search_result(
        self,
        spans: tuple[SearchSpan, ...],
        selection: SearchSelection,
    ) -> None:
        """Move to and highlight a resolved search result in this pane."""
        self._search_current_selection = selection
        start, _end = spans[selection.index]
        self.cursor_location = self._location_from_absolute(start)
        self._set_search_highlights(
            spans,
            current_index=selection.index,
        )

    def _clear_prompt_search_result(self) -> None:
        """Clear the selected repeat result and its transient highlights."""
        self._search_current_selection = None
        self._clear_search_highlights()

    def _show_prompt_search_feedback(self, message: str) -> None:
        """Surface non-blocking prompt-search feedback."""
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify(message, severity="information")
