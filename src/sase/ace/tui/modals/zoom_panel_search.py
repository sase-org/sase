"""Zoom-panel adapter for the shared Vim-style search controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.events import Key
from textual.widgets import Static

from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
    invert_search_direction,
    line_start_offsets as _line_start_offsets,
    offset_for_row as _offset_for_row,
    offset_to_row_col as _offset_to_row_col,
    wrap_feedback_message,
)

from .zoom_panel_navigation import zoom_target_view_selector
from .zoom_panel_types import _TARGET_ORDER, ZoomPanelTarget
from .zoom_panel_widgets import ZoomFilePanel, ZoomToolsPanel

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


ZoomSearchMode = VimSearchMode

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


class ZoomSearchMixin(_MixinBase):
    """Re-host shared incremental Vim search inside ``ZoomPanelModal``."""

    if TYPE_CHECKING:
        _target: ZoomPanelTarget
        _refresh_timer: Any | None

        def _active_scroll(self) -> VerticalScroll: ...
        def _refresh_active_panel(self, *, force: bool) -> None: ...
        def _show_target(self, target: ZoomPanelTarget) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._zoom_search = VimSearchController(self)
        self._zoom_search_refresh_paused = False
        super().__init__(*args, **kwargs)

    @property
    def _zoom_search_mode(self) -> VimSearchMode:
        """Compatibility view of the controller's current mode."""
        return self._zoom_search.mode

    @property
    def _zoom_search_direction(self) -> SearchDirection:
        """Compatibility view of the controller's search direction."""
        return self._zoom_search.direction

    @property
    def _zoom_search_query(self) -> str:
        """Compatibility view of the controller's editable query."""
        return self._zoom_search.query

    @property
    def _zoom_search_corpus(self) -> str:
        """Compatibility view of the controller's immutable corpus."""
        return self._zoom_search.corpus

    @property
    def _zoom_search_line_starts(self) -> tuple[int, ...]:
        """Compatibility view of logical-line offsets in the corpus."""
        return self._zoom_search.line_starts

    @property
    def _zoom_search_match_spans(self) -> tuple[SearchSpan, ...]:
        """Compatibility view of all current match spans."""
        return self._zoom_search.match_spans

    @property
    def _zoom_search_current_selection(self) -> SearchSelection | None:
        """Compatibility view of the controller's current match."""
        return self._zoom_search.current_selection

    @property
    def _zoom_search_origin_offset(self) -> int:
        """Compatibility view of the incremental-search origin."""
        return self._zoom_search.origin_offset

    @property
    def _zoom_search_restore_scroll_x(self) -> int:
        """Compatibility view of the native horizontal restore offset."""
        return self._zoom_search.restore_scroll_x

    @property
    def _zoom_search_restore_scroll_y(self) -> int:
        """Compatibility view of the native vertical restore offset."""
        return self._zoom_search.restore_scroll_y

    @property
    def _last_zoom_search(self) -> tuple[str, SearchDirection] | None:
        """Compatibility view of the last committed search."""
        return self._zoom_search.last_search

    def _is_zoom_search_active(self) -> bool:
        """Return whether the zoom search overlay currently owns the view."""
        return self._zoom_search.is_active

    def _is_zoom_search_overlay_visible(self) -> bool:
        """Return whether the search scroll should be the active scroll."""
        return self._is_zoom_search_active()

    def _handle_zoom_search_key(self, event: Key) -> bool:
        """Handle a key before modal bindings run.

        Structural keys in committed search tear down the controller and pass
        through so the normal zoom-modal binding can still execute.
        """
        disposition = self._zoom_search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=_STRUCTURAL_SEARCH_EXIT_KEYS,
        )
        return disposition == "consumed"

    def _start_zoom_search(self, direction: SearchDirection) -> None:
        """Open incremental search over the active zoom panel."""
        self._zoom_search.start(direction)

    def _exit_zoom_search(
        self,
        *,
        restore_scroll: bool,
        refresh: bool,
        restore_from_current_overlay: bool = False,
    ) -> None:
        """Tear down zoom search and optionally restore the native scroll."""
        self._zoom_search.exit(
            restore_scroll=restore_scroll,
            refresh=refresh,
            restore_from_current_overlay=restore_from_current_overlay,
        )

    def _repeat_zoom_search(self, *, reverse: bool = False) -> None:
        """Move to the next or previous committed match."""
        self._zoom_search.repeat(reverse=reverse)

    def _zoom_searchable_text(self) -> str:
        """Extract text that can be highlighted inside the search overlay."""
        return self.vim_search_corpus()

    def vim_search_corpus(self) -> str:
        """Return searchable text for the active zoom target."""
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

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        """Return the active zoom view's current scroll position."""
        origin_scroll = self._active_scroll()
        return (int(origin_scroll.scroll_x), int(origin_scroll.scroll_y))

    def vim_search_overlay_viewport(self) -> SearchViewport:
        """Return the zoom search overlay's scroll and viewport geometry."""
        scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=scroll.scrollable_content_region.width,
            height=scroll.scrollable_content_region.height,
        )

    def vim_search_started(self) -> None:
        """Pause modal-local refresh while the frozen overlay is active."""
        self._pause_zoom_search_refresh()

    def vim_search_exited(self, *, refresh: bool) -> None:
        """Resume modal-local refresh after the overlay is hidden."""
        self._resume_zoom_search_refresh(force_refresh=refresh)

    def vim_search_show_overlay(self) -> None:
        """Hide native zoom scrolls and reveal the search-owned scroll."""
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
            self.query_one(zoom_target_view_selector(target)).add_class("hidden")
        search_scroll = self.query_one("#zoom-search-scroll", VerticalScroll)
        search_scroll.border_subtitle = subtitle
        search_scroll.remove_class("hidden")
        command = self.query_one("#zoom-search-command", Static)
        command.border_title = "search"
        command.remove_class("hidden")

    def vim_search_hide_overlay(self) -> None:
        """Hide the search overlay and restore the native active panel."""
        self.query_one("#zoom-search-panel", Static).update("")
        self.query_one("#zoom-search-scroll", VerticalScroll).add_class("hidden")
        command = self.query_one("#zoom-search-command", Static)
        command.update("")
        command.border_title = ""
        command.border_subtitle = ""
        command.add_class("hidden")
        self._show_target(self._target)

    def vim_search_paint_overlay(self, content: Text) -> None:
        """Paint controller-rendered content into the zoom overlay."""
        self.query_one("#zoom-search-panel", Static).update(content)

    def vim_search_command_width(self) -> int:
        """Return usable width inside the zoom search command border."""
        command = self.query_one("#zoom-search-command", Static)
        return max(0, int(getattr(command.size, "width", 0)) - 4)

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        """Paint controller-rendered command content with zoom-specific hints."""
        command = self.query_one("#zoom-search-command", Static)
        command.border_title = "search"
        if mode == "typing":
            command.border_subtitle = "[enter] accept  [esc/^c] cancel"
        else:
            command.border_subtitle = "[n/N] next/prev  [esc] close search"
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        """Scroll the zoom search overlay immediately."""
        self.query_one("#zoom-search-scroll", VerticalScroll).scroll_to(
            x=x,
            y=y,
            animate=False,
            immediate=True,
        )

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        """Restore the current native zoom target after the next refresh."""
        target = self._target

        def restore() -> None:
            self._restore_zoom_native_scroll(target, x, y)

        self.call_after_refresh(restore)

    def vim_search_focus_overlay(self) -> None:
        """Focus the overlay after it becomes visible."""
        self.call_after_refresh(self._focus_zoom_search_scroll)

    def vim_search_focus_native(self) -> None:
        """Focus the native zoom scroll after the overlay is hidden."""
        self.call_after_refresh(self._focus_native_zoom_scroll)

    def vim_search_notify(self, message: str) -> None:
        """Surface non-blocking zoom-search feedback."""
        self.notify(message, severity="information")

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
        return invert_search_direction(direction)

    @staticmethod
    def _wrap_feedback_message(direction: SearchDirection) -> str:
        """Return Vim-style wrap feedback for ``direction``."""
        return wrap_feedback_message(direction)

    def _show_zoom_search_feedback(self, message: str) -> None:
        """Surface non-blocking zoom-search feedback."""
        self.vim_search_notify(message)


__all__ = [
    "ZoomSearchMixin",
    "ZoomSearchMode",
    "_line_start_offsets",
    "_offset_for_row",
    "_offset_to_row_col",
]
