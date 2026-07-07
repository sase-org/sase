"""Vim-style search overlay for the Agents-tab zoom panel modal."""

from __future__ import annotations

from bisect import bisect_right
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.containers import VerticalScroll
from textual.events import Key
from textual.widgets import Static

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
    select_search_match,
)
from sase.ace.tui.widgets.search_command_line import render_search_command_line

from .zoom_panel_rendering import renderable_to_text
from .zoom_panel_types import _TARGET_ORDER, ZoomPanelTarget
from .zoom_panel_widgets import ZoomFilePanel, ZoomToolsPanel

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


ZoomSearchMode = Literal["off", "typing", "committed"]

_MATCH_STYLE = "on #585858"
_CURRENT_MATCH_STYLE = "bold black on #FFD787"
_SCROLL_CONTEXT_ROWS = 3
_STRUCTURAL_SEARCH_EXIT_KEYS = {
    "right_square_bracket",
    "left_square_bracket",
    "ctrl+n",
    "ctrl+p",
    "equals_sign",
    "minus",
    "h",
    "l",
    "H",
    "L",
    "E",
    "r",
    "q",
    "z",
}


def _line_start_offsets(text: str) -> tuple[int, ...]:
    """Return absolute offsets for the first character of every logical line."""
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return tuple(starts)


def _offset_to_row_col(
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


def _offset_for_row(line_starts: tuple[int, ...], row: int) -> int:
    """Return the absolute offset for the start of ``row``."""
    if not line_starts:
        return 0
    clamped_row = min(max(0, row), len(line_starts) - 1)
    return line_starts[clamped_row]


class ZoomSearchMixin(_MixinBase):
    """Incremental Vim-style search for ``ZoomPanelModal``."""

    if TYPE_CHECKING:
        _target: ZoomPanelTarget
        _refresh_timer: Any | None

        def _active_scroll(self) -> VerticalScroll: ...
        def _refresh_active_panel(self, *, force: bool) -> None: ...
        def _show_target(self, target: ZoomPanelTarget) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._zoom_search_mode: ZoomSearchMode = "off"
        self._zoom_search_direction: SearchDirection = "forward"
        self._zoom_search_query = ""
        self._zoom_search_corpus = ""
        self._zoom_search_line_starts: tuple[int, ...] = (0,)
        self._zoom_search_match_spans: tuple[SearchSpan, ...] = ()
        self._zoom_search_current_selection: SearchSelection | None = None
        self._zoom_search_origin_offset = 0
        self._zoom_search_restore_scroll_x = 0
        self._zoom_search_restore_scroll_y = 0
        self._last_zoom_search: tuple[str, SearchDirection] | None = None
        self._zoom_search_refresh_paused = False
        super().__init__(*args, **kwargs)

    def _is_zoom_search_active(self) -> bool:
        """Return whether the zoom search overlay currently owns the view."""
        return self._zoom_search_mode != "off"

    def _is_zoom_search_overlay_visible(self) -> bool:
        """Return whether the search scroll should be the active scroll."""
        return self._is_zoom_search_active()

    def _handle_zoom_search_key(self, event: Key) -> bool:
        """Handle a key before modal bindings run.

        Returns ``True`` when the key is consumed. Structural keys in committed
        search return ``False`` after tearing down search so the normal binding
        can still execute.
        """
        if self._zoom_search_mode == "typing":
            return self._handle_zoom_search_typing_key(event)

        if self._zoom_search_mode == "committed":
            if event.key == "escape":
                self._exit_zoom_search(
                    restore_scroll=True,
                    restore_from_current_overlay=True,
                    refresh=True,
                )
                return True
            if event.key == "n":
                self._repeat_zoom_search(reverse=False)
                return True
            if event.key == "N":
                self._repeat_zoom_search(reverse=True)
                return True
            if event.key == "slash":
                self._start_zoom_search("forward")
                return True
            if event.key == "question_mark":
                self._start_zoom_search("reverse")
                return True
            if event.key in _STRUCTURAL_SEARCH_EXIT_KEYS:
                self._exit_zoom_search(restore_scroll=False, refresh=False)
                return False

        if event.key == "slash":
            self._start_zoom_search("forward")
            return True
        if event.key == "question_mark":
            self._start_zoom_search("reverse")
            return True
        return False

    def _start_zoom_search(self, direction: SearchDirection) -> None:
        """Open an incremental search over the active panel's text."""
        corpus = self._zoom_searchable_text()
        if not corpus:
            self.notify("Nothing to search", severity="information")
            return

        origin_scroll = self._active_scroll()
        self._zoom_search_restore_scroll_x = int(origin_scroll.scroll_x)
        self._zoom_search_restore_scroll_y = int(origin_scroll.scroll_y)
        self._zoom_search_line_starts = _line_start_offsets(corpus)
        self._zoom_search_origin_offset = _offset_for_row(
            self._zoom_search_line_starts,
            self._zoom_search_restore_scroll_y,
        )
        self._zoom_search_corpus = corpus
        self._zoom_search_direction = direction
        self._zoom_search_query = ""
        self._zoom_search_match_spans = ()
        self._zoom_search_current_selection = None
        self._zoom_search_mode = "typing"

        self._pause_zoom_search_refresh()
        self._show_zoom_search_overlay()
        self._render_zoom_search_overlay()
        self._render_zoom_search_command_line()
        self.call_after_refresh(self._focus_zoom_search_scroll)

    def _handle_zoom_search_typing_key(self, event: Key) -> bool:
        """Handle all keys while the search command line is being edited."""
        if event.key in {"escape", "ctrl+c"}:
            self._cancel_zoom_search()
            return True
        if event.key == "enter":
            self._confirm_zoom_search()
            return True
        if event.key in {"backspace", "ctrl+h"}:
            if self._zoom_search_query:
                self._zoom_search_query = self._zoom_search_query[:-1]
                self._update_zoom_search_preview()
            return True

        char = event.character
        if char is not None and len(char) == 1 and event.key != "tab":
            self._zoom_search_query += char
            self._update_zoom_search_preview()
            return True

        return True

    def _update_zoom_search_preview(self) -> None:
        """Refresh matches, highlights, count display, and preview scroll."""
        query = self._zoom_search_query
        if not query:
            self._zoom_search_match_spans = ()
            self._zoom_search_current_selection = None
            self._render_zoom_search_overlay()
            self._render_zoom_search_command_line()
            self._scroll_zoom_search_to_origin()
            return

        spans = find_search_matches(self._zoom_search_corpus, query)
        selection = select_search_match(
            spans,
            self._zoom_search_origin_offset,
            self._zoom_search_direction,
            include_origin=True,
        )
        self._zoom_search_match_spans = spans
        self._zoom_search_current_selection = selection
        self._render_zoom_search_overlay()
        self._render_zoom_search_command_line()
        if selection is None:
            self._scroll_zoom_search_to_origin()
        else:
            self._scroll_zoom_search_to_selection(selection)

    def _confirm_zoom_search(self) -> None:
        """Commit search highlights and keep the overlay open for ``n``/``N``."""
        if not self._zoom_search_query or self._zoom_search_current_selection is None:
            self._exit_zoom_search(restore_scroll=True, refresh=True)
            return
        self._last_zoom_search = (
            self._zoom_search_query,
            self._zoom_search_direction,
        )
        self._zoom_search_mode = "committed"
        self._render_zoom_search_command_line()

    def _cancel_zoom_search(self) -> None:
        """Cancel incremental search and restore the pre-search native view."""
        self._exit_zoom_search(restore_scroll=True, refresh=True)

    def _exit_zoom_search(
        self,
        *,
        restore_scroll: bool,
        refresh: bool,
        restore_from_current_overlay: bool = False,
    ) -> None:
        """Tear down search and optionally restore a native-panel scroll offset."""
        if not self._is_zoom_search_active():
            return

        restore_x = self._zoom_search_restore_scroll_x
        restore_y = self._zoom_search_restore_scroll_y
        if restore_from_current_overlay:
            search_scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
            restore_x = int(search_scroll.scroll_x)
            restore_y = int(search_scroll.scroll_y)

        self._zoom_search_mode = "off"
        self._zoom_search_query = ""
        self._zoom_search_match_spans = ()
        self._zoom_search_current_selection = None
        self._hide_zoom_search_overlay()
        self._resume_zoom_search_refresh(force_refresh=refresh)
        if restore_scroll:
            target = self._target

            def restore() -> None:
                self._restore_zoom_native_scroll(target, restore_x, restore_y)

            self.call_after_refresh(restore)
        else:
            self.call_after_refresh(self._focus_native_zoom_scroll)

    def _repeat_zoom_search(self, *, reverse: bool = False) -> None:
        """Move to the next or previous committed match."""
        if self._last_zoom_search is None:
            self._show_zoom_search_feedback("no previous search")
            return

        query, recorded_direction = self._last_zoom_search
        direction = (
            self._invert_search_direction(recorded_direction)
            if reverse
            else recorded_direction
        )
        origin = self._current_zoom_search_origin()
        spans = find_search_matches(self._zoom_search_corpus, query)
        selection = select_search_match(
            spans,
            origin,
            direction,
            include_origin=False,
        )
        if selection is None:
            self._zoom_search_match_spans = ()
            self._zoom_search_current_selection = None
            self._render_zoom_search_overlay()
            self._render_zoom_search_command_line()
            self._show_zoom_search_feedback("pattern not found")
            return

        self._zoom_search_query = query
        self._zoom_search_direction = recorded_direction
        self._zoom_search_match_spans = spans
        self._zoom_search_current_selection = selection
        self._render_zoom_search_overlay()
        self._render_zoom_search_command_line()
        self._scroll_zoom_search_to_selection(selection)
        if selection.wrapped:
            self._show_zoom_search_feedback(self._wrap_feedback_message(direction))

    def _current_zoom_search_origin(self) -> int:
        """Return the absolute offset of the current match or viewport top."""
        selection = self._zoom_search_current_selection
        if selection is not None and 0 <= selection.index < len(
            self._zoom_search_match_spans
        ):
            start, _end = self._zoom_search_match_spans[selection.index]
            return start
        search_scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        return _offset_for_row(
            self._zoom_search_line_starts, int(search_scroll.scroll_y)
        )

    def _zoom_searchable_text(self) -> str:
        """Extract text that can be highlighted inside the search overlay."""
        if self._target == ZoomPanelTarget.FILE:
            file_panel = self.query_one("#zoom-file-panel", ZoomFilePanel)
            content = file_panel.get_current_content()
            if content:
                return content
            full_content = getattr(file_panel, "_full_content", None)
            return full_content if isinstance(full_content, str) else ""
        if self._target == ZoomPanelTarget.TOOLS:
            content = self.query_one(
                "#zoom-tools-panel", ZoomToolsPanel
            ).get_tools_text()
            return content or ""

        active_panel = self.query_one(f"#zoom-{self._target.value}-panel", Static)
        return renderable_to_text(getattr(active_panel, "content", None)) or ""

    def _show_zoom_search_overlay(self) -> None:
        """Hide native scrolls and reveal the search-owned scroll."""
        subtitle = ""
        try:
            native_scroll = self.query_one(
                f"#zoom-{self._target.value}-scroll",
                VerticalScroll,
            )
            subtitle = native_scroll.border_subtitle or ""
        except Exception:
            pass
        for target in _TARGET_ORDER:
            self.query_one(f"#zoom-{target.value}-scroll", VerticalScroll).add_class(
                "hidden"
            )
        search_scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        search_scroll.border_subtitle = subtitle
        search_scroll.remove_class("hidden")
        command = self.query_one("#zoom-search-command", Static)
        command.border_title = "search"
        command.remove_class("hidden")

    def _hide_zoom_search_overlay(self) -> None:
        """Hide the search overlay and restore the native active panel."""
        search_panel = self.query_one("#zoom-search-panel", Static)
        search_panel.update("")
        self.query_one("#zoom-search-scroll", VerticalScroll).add_class("hidden")
        command = self.query_one("#zoom-search-command", Static)
        command.update("")
        command.border_title = ""
        command.border_subtitle = ""
        command.add_class("hidden")
        self._show_target(self._target)

    def _render_zoom_search_overlay(self) -> None:
        """Paint the search corpus with all-match and current-match highlights."""
        body = Text(self._zoom_search_corpus, no_wrap=True, overflow="crop")
        for start, end in self._zoom_search_match_spans:
            if end > start:
                body.stylize(_MATCH_STYLE, start, end)
        selection = self._zoom_search_current_selection
        if selection is not None and 0 <= selection.index < len(
            self._zoom_search_match_spans
        ):
            start, end = self._zoom_search_match_spans[selection.index]
            if end > start:
                body.stylize(_CURRENT_MATCH_STYLE, start, end)
        self.query_one("#zoom-search-panel", Static).update(body)

    def _render_zoom_search_command_line(self) -> None:
        command = self.query_one("#zoom-search-command", Static)
        command.border_title = "search"
        if self._zoom_search_mode == "typing":
            command.border_subtitle = "[enter] accept  [esc/^c] cancel"
        else:
            command.border_subtitle = "[n/N] next/prev  [esc] close search"
        selection = self._zoom_search_current_selection
        width = max(0, int(getattr(command.size, "width", 0)) - 4)
        command.update(
            render_search_command_line(
                direction=self._zoom_search_direction,
                query=self._zoom_search_query,
                current_index=selection.index if selection is not None else None,
                total=len(self._zoom_search_match_spans),
                width=width,
            )
        )
        command.remove_class("hidden")

    def _scroll_zoom_search_to_origin(self) -> None:
        scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        row, _col = _offset_to_row_col(
            self._zoom_search_line_starts,
            self._zoom_search_origin_offset,
        )
        scroll.scroll_to(
            x=self._zoom_search_restore_scroll_x,
            y=row,
            animate=False,
            immediate=True,
        )

    def _scroll_zoom_search_to_selection(self, selection: SearchSelection) -> None:
        if not (0 <= selection.index < len(self._zoom_search_match_spans)):
            return
        start, _end = self._zoom_search_match_spans[selection.index]
        row, column = _offset_to_row_col(self._zoom_search_line_starts, start)
        scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        viewport_height = max(1, scroll.scrollable_content_region.height)
        viewport_width = max(1, scroll.scrollable_content_region.width)
        current_y = int(scroll.scroll_y)
        current_x = int(scroll.scroll_x)

        target_y = current_y
        if row < current_y + 1 or row >= current_y + viewport_height - 1:
            target_y = max(0, row - _SCROLL_CONTEXT_ROWS)

        target_x = current_x
        if column < current_x or column >= current_x + viewport_width - 4:
            target_x = max(0, column - 4)

        scroll.scroll_to(x=target_x, y=target_y, animate=False, immediate=True)

    def _restore_zoom_native_scroll(
        self,
        target: ZoomPanelTarget,
        x: int,
        y: int,
    ) -> None:
        if self._target != target:
            return
        scroll = self.query_one(f"#zoom-{target.value}-scroll", VerticalScroll)
        scroll.scroll_to(x=x, y=y, animate=False, immediate=True)
        try:
            scroll.focus()
        except Exception:
            pass

    def _focus_zoom_search_scroll(self) -> None:
        try:
            self.query_one("#zoom-search-scroll", VerticalScroll).focus()
        except Exception:
            pass

    def _focus_native_zoom_scroll(self) -> None:
        try:
            self.query_one(f"#zoom-{self._target.value}-scroll", VerticalScroll).focus()
        except Exception:
            pass

    def _pause_zoom_search_refresh(self) -> None:
        if self._zoom_search_refresh_paused:
            return
        timer = self._refresh_timer
        if timer is None:
            return
        timer.pause()
        self._zoom_search_refresh_paused = True

    def _resume_zoom_search_refresh(self, *, force_refresh: bool) -> None:
        if self._zoom_search_refresh_paused:
            timer = self._refresh_timer
            if timer is not None:
                timer.resume()
            self._zoom_search_refresh_paused = False
        if force_refresh:
            self._refresh_active_panel(force=True)

    @staticmethod
    def _invert_search_direction(direction: SearchDirection) -> SearchDirection:
        """Return the opposite search direction."""
        return "reverse" if direction == "forward" else "forward"

    @staticmethod
    def _wrap_feedback_message(direction: SearchDirection) -> str:
        """Return Vim-style wrap feedback for *direction*."""
        if direction == "forward":
            return "search hit BOTTOM, continuing at TOP"
        return "search hit TOP, continuing at BOTTOM"

    def _show_zoom_search_feedback(self, message: str) -> None:
        """Surface non-blocking zoom-search feedback."""
        self.notify(message, severity="information")
