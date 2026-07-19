"""Host-agnostic controller for Vim-style incremental text search."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal, Protocol

from rich.text import Text

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
    select_search_match,
)
from sase.ace.tui.widgets.search_command_line import render_search_command_line

VimSearchMode = Literal["off", "typing", "committed"]
SearchKeyDisposition = Literal["consumed", "passthrough", "ignored"]

MATCH_STYLE = "on #585858"
CURRENT_MATCH_STYLE = "bold black on #FFD787"
SCROLL_CONTEXT_ROWS = 3


@dataclass(frozen=True)
class SearchViewport:
    """Current search-overlay scroll position and visible dimensions."""

    scroll_x: int
    scroll_y: int
    width: int
    height: int


class _VimSearchHost(Protocol):
    """UI operations required by :class:`VimSearchController`."""

    def vim_search_corpus(self) -> str:
        """Return the immutable text corpus for a newly-started search."""

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        """Return the active view's current ``(x, y)`` scroll position."""

    def vim_search_overlay_viewport(self) -> SearchViewport:
        """Return the search overlay's current scroll position and dimensions."""

    def vim_search_started(self) -> None:
        """Run host-specific work immediately before showing the overlay."""

    def vim_search_exited(self, *, refresh: bool) -> None:
        """Run host-specific work after hiding the overlay."""

    def vim_search_show_overlay(self) -> None:
        """Show the search overlay."""

    def vim_search_hide_overlay(self) -> None:
        """Hide and clear the search overlay."""

    def vim_search_paint_overlay(self, content: Text) -> None:
        """Paint highlighted search content into the overlay."""

    def vim_search_command_width(self) -> int:
        """Return the usable width of the search command line."""

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        """Paint the search command line for ``mode``."""

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        """Scroll the search overlay immediately to ``(x, y)``."""

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        """Restore the native view to ``(x, y)`` and focus it."""

    def vim_search_focus_overlay(self) -> None:
        """Focus the search overlay after it becomes visible."""

    def vim_search_focus_native(self) -> None:
        """Focus the native view after the overlay is hidden."""

    def vim_search_notify(self, message: str) -> None:
        """Surface non-blocking search feedback."""


def line_start_offsets(text: str) -> tuple[int, ...]:
    """Return absolute offsets for the first character of every logical line."""
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return tuple(starts)


def offset_to_row_col(
    line_starts: tuple[int, ...],
    offset: int,
) -> tuple[int, int]:
    """Map an absolute offset to ``(row, column)`` within ``line_starts``."""
    if not line_starts:
        return (0, 0)
    clamped = max(0, offset)
    row = max(0, bisect_right(line_starts, clamped) - 1)
    row = min(row, len(line_starts) - 1)
    return (row, clamped - line_starts[row])


def offset_for_row(line_starts: tuple[int, ...], row: int) -> int:
    """Return the absolute offset for the start of ``row``."""
    if not line_starts:
        return 0
    clamped_row = min(max(0, row), len(line_starts) - 1)
    return line_starts[clamped_row]


def invert_search_direction(direction: SearchDirection) -> SearchDirection:
    """Return the opposite search direction."""
    return "reverse" if direction == "forward" else "forward"


def wrap_feedback_message(direction: SearchDirection) -> str:
    """Return Vim-style wrap feedback for ``direction``."""
    if direction == "forward":
        return "search hit BOTTOM, continuing at TOP"
    return "search hit TOP, continuing at BOTTOM"


class VimSearchController:
    """Incremental Vim search state machine backed by a small host protocol."""

    def __init__(self, host: _VimSearchHost) -> None:
        self._host = host
        self.mode: VimSearchMode = "off"
        self.direction: SearchDirection = "forward"
        self.query = ""
        self.corpus = ""
        self.line_starts: tuple[int, ...] = (0,)
        self.match_spans: tuple[SearchSpan, ...] = ()
        self.current_selection: SearchSelection | None = None
        self.origin_offset = 0
        self.restore_scroll_x = 0
        self.restore_scroll_y = 0
        self.last_search: tuple[str, SearchDirection] | None = None

    @property
    def is_active(self) -> bool:
        """Return whether search currently owns its host's view."""
        return self.mode != "off"

    def start(self, direction: SearchDirection) -> bool:
        """Start an incremental search, returning whether a corpus was available."""
        corpus = self._host.vim_search_corpus()
        if not corpus:
            self._host.vim_search_notify("Nothing to search")
            return False

        origin_x, origin_y = self._host.vim_search_origin_scroll()
        self.restore_scroll_x = origin_x
        self.restore_scroll_y = origin_y
        self.line_starts = line_start_offsets(corpus)
        self.origin_offset = offset_for_row(self.line_starts, origin_y)
        self.corpus = corpus
        self.direction = direction
        self.query = ""
        self.match_spans = ()
        self.current_selection = None
        self.mode = "typing"

        self._host.vim_search_started()
        self._host.vim_search_show_overlay()
        self._render_overlay()
        self._render_command_line()
        self._host.vim_search_focus_overlay()
        return True

    def handle_key(
        self,
        key: str,
        character: str | None,
        *,
        passthrough_exit_keys: Collection[str] | None = (),
    ) -> SearchKeyDisposition:
        """Interpret one key and report whether its host should also handle it.

        ``passthrough_exit_keys=None`` makes every otherwise-unhandled key exit
        committed mode before passing through. A concrete collection limits
        that behavior to the supplied structural keys.
        """
        if self.mode == "typing":
            return self._handle_typing_key(key, character)

        if self.mode == "committed":
            if key == "escape":
                self.exit(
                    restore_scroll=True,
                    restore_from_current_overlay=True,
                    refresh=True,
                )
                return "consumed"
            if key == "n":
                self.repeat(reverse=False)
                return "consumed"
            if key == "N":
                self.repeat(reverse=True)
                return "consumed"
            if key == "slash":
                self.start("forward")
                return "consumed"
            if key == "question_mark":
                self.start("reverse")
                return "consumed"
            if passthrough_exit_keys is None or key in passthrough_exit_keys:
                self.exit(restore_scroll=False, refresh=False)
                return "passthrough"

        if key == "slash":
            self.start("forward")
            return "consumed"
        if key == "question_mark":
            self.start("reverse")
            return "consumed"
        return "ignored"

    def repeat(self, *, reverse: bool = False) -> None:
        """Move to the next or previous committed match."""
        if self.last_search is None:
            self._host.vim_search_notify("no previous search")
            return

        query, recorded_direction = self.last_search
        direction = (
            invert_search_direction(recorded_direction)
            if reverse
            else recorded_direction
        )
        origin = self._current_origin()
        spans = find_search_matches(self.corpus, query)
        selection = select_search_match(
            spans,
            origin,
            direction,
            include_origin=False,
        )
        if selection is None:
            self.match_spans = ()
            self.current_selection = None
            self._render_overlay()
            self._render_command_line()
            self._host.vim_search_notify("pattern not found")
            return

        self.query = query
        self.direction = recorded_direction
        self.match_spans = spans
        self.current_selection = selection
        self._render_overlay()
        self._render_command_line()
        self._scroll_to_selection(selection)
        if selection.wrapped:
            self._host.vim_search_notify(wrap_feedback_message(direction))

    def exit(
        self,
        *,
        restore_scroll: bool,
        refresh: bool,
        restore_from_current_overlay: bool = False,
    ) -> None:
        """Tear down search and optionally restore a native-view scroll offset."""
        if not self.is_active:
            return

        restore_x = self.restore_scroll_x
        restore_y = self.restore_scroll_y
        if restore_from_current_overlay:
            viewport = self._host.vim_search_overlay_viewport()
            restore_x = viewport.scroll_x
            restore_y = viewport.scroll_y

        self.mode = "off"
        self.query = ""
        self.match_spans = ()
        self.current_selection = None
        self._host.vim_search_hide_overlay()
        self._host.vim_search_exited(refresh=refresh)
        if restore_scroll:
            self._host.vim_search_restore_scroll(x=restore_x, y=restore_y)
        else:
            self._host.vim_search_focus_native()

    def _handle_typing_key(
        self,
        key: str,
        character: str | None,
    ) -> SearchKeyDisposition:
        if key in {"escape", "ctrl+c"}:
            self.exit(restore_scroll=True, refresh=True)
            return "consumed"
        if key == "enter":
            self._confirm()
            return "consumed"
        if key in {"backspace", "ctrl+h"}:
            if self.query:
                self.query = self.query[:-1]
                self._update_preview()
            return "consumed"

        if character is not None and len(character) == 1 and key != "tab":
            self.query += character
            self._update_preview()
        return "consumed"

    def _update_preview(self) -> None:
        if not self.query:
            self.match_spans = ()
            self.current_selection = None
            self._render_overlay()
            self._render_command_line()
            self._scroll_to_origin()
            return

        spans = find_search_matches(self.corpus, self.query)
        selection = select_search_match(
            spans,
            self.origin_offset,
            self.direction,
            include_origin=True,
        )
        self.match_spans = spans
        self.current_selection = selection
        self._render_overlay()
        self._render_command_line()
        if selection is None:
            self._scroll_to_origin()
        else:
            self._scroll_to_selection(selection)

    def _confirm(self) -> None:
        if not self.query or self.current_selection is None:
            self.exit(restore_scroll=True, refresh=True)
            return
        self.last_search = (self.query, self.direction)
        self.mode = "committed"
        self._render_command_line()

    def _current_origin(self) -> int:
        selection = self.current_selection
        if selection is not None and 0 <= selection.index < len(self.match_spans):
            start, _end = self.match_spans[selection.index]
            return start
        viewport = self._host.vim_search_overlay_viewport()
        return offset_for_row(self.line_starts, viewport.scroll_y)

    def _render_overlay(self) -> None:
        body = Text(self.corpus, no_wrap=True, overflow="crop")
        for start, end in self.match_spans:
            if end > start:
                body.stylize(MATCH_STYLE, start, end)
        selection = self.current_selection
        if selection is not None and 0 <= selection.index < len(self.match_spans):
            start, end = self.match_spans[selection.index]
            if end > start:
                body.stylize(CURRENT_MATCH_STYLE, start, end)
        self._host.vim_search_paint_overlay(body)

    def _render_command_line(self) -> None:
        selection = self.current_selection
        content = render_search_command_line(
            direction=self.direction,
            query=self.query,
            current_index=selection.index if selection is not None else None,
            total=len(self.match_spans),
            width=max(0, self._host.vim_search_command_width()),
        )
        self._host.vim_search_paint_command_line(content, self.mode)

    def _scroll_to_origin(self) -> None:
        row, _col = offset_to_row_col(self.line_starts, self.origin_offset)
        self._host.vim_search_scroll_overlay(x=self.restore_scroll_x, y=row)

    def _scroll_to_selection(self, selection: SearchSelection) -> None:
        if not (0 <= selection.index < len(self.match_spans)):
            return
        start, _end = self.match_spans[selection.index]
        row, column = offset_to_row_col(self.line_starts, start)
        viewport = self._host.vim_search_overlay_viewport()
        viewport_height = max(1, viewport.height)
        viewport_width = max(1, viewport.width)

        target_y = viewport.scroll_y
        if (
            row < viewport.scroll_y + 1
            or row >= viewport.scroll_y + viewport_height - 1
        ):
            target_y = max(0, row - SCROLL_CONTEXT_ROWS)

        target_x = viewport.scroll_x
        if (
            column < viewport.scroll_x
            or column >= viewport.scroll_x + viewport_width - 4
        ):
            target_x = max(0, column - 4)

        self._host.vim_search_scroll_overlay(x=target_x, y=target_y)


__all__ = [
    "CURRENT_MATCH_STYLE",
    "MATCH_STYLE",
    "SCROLL_CONTEXT_ROWS",
    "SearchKeyDisposition",
    "SearchViewport",
    "VimSearchController",
    "VimSearchMode",
    "invert_search_direction",
    "line_start_offsets",
    "offset_for_row",
    "offset_to_row_col",
    "wrap_feedback_message",
]
