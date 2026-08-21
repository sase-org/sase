"""Filter input widget for the XPrompt browser pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Input

from ..actions.navigation.jump_hints import normalize_jump_key

if TYPE_CHECKING:
    from .xprompt_browser_pane import XPromptBrowserPane


class BrowserFilterInput(Input):
    """Explicitly opened text editor for the XPrompt browser filter.

    The row list owns focus until ``/`` reveals this widget. Printable
    characters -- including a leading digit or apostrophe -- are filter text.
    Ctrl-key combinations keep preview scrolling and list motion available
    while typing. When embedded in Config, brackets cycle Config sub-tabs,
    while the Admin Center's priority ``Tab`` / ``Shift+Tab`` bindings handle
    main-tab navigation. Enter and Escape finish the filter session. While
    jump mode is still active, every key is routed to the jump state machine
    first, so Escape cancels jump before it can close the editor.
    """

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Prev"),
        ("enter", "close_filter", "Done"),
        ("escape", "close_filter", "Close filter"),
        ("ctrl+o", "forward('add_xprompt')", "Add"),
        ("ctrl+i", "forward('load_xprompt')", "Load"),
    ]

    def on_key(self, event: events.Key) -> None:
        """Give jump cancellation first refusal, then Config bracket cycling.

        Printable keys, including empty-filter digits and apostrophe, stay
        ordinary editor text. ``Ctrl+I`` remains the explicit inline-load
        binding when the terminal reports it distinctly. A bare ``Tab``
        always reaches the Admin Center's priority next-tab binding.
        """
        pane = self._pane()
        if pane is not None and pane.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if pane.handle_jump_key(key):
                event.stop()
                event.prevent_default()
            return

        from .config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)

    def _pane(self) -> XPromptBrowserPane | None:
        """Return the owning :class:`XPromptBrowserPane`, if any."""
        node: object | None = self.parent
        while node is not None:
            if _looks_like_browser_pane(node):
                return cast("XPromptBrowserPane", node)
            node = getattr(node, "parent", None)
        return None

    def action_close_filter(self) -> None:
        """Keep the applied query and return focus to the row list."""
        pane = self._pane()
        if pane is not None:
            pane._close_filter()

    def action_forward(self, action_name: str) -> None:
        """Forward an action to the owning pane."""
        pane = self._pane()
        if pane is not None:
            getattr(pane, f"action_{action_name}")()

    def action_scroll_preview_down(self) -> None:
        """Scroll the preview panel down."""
        pane = self._pane()
        if pane is not None:
            pane.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        """Scroll preview up, or clear input if already at top."""
        pane = self._pane()
        if pane is None:
            return
        scroll = pane.query_one("#browser-preview-scroll", VerticalScroll)
        if scroll.scroll_y > 0:
            pane.scroll_preview_up()
        elif self.cursor_position > 0:
            self.value = self.value[self.cursor_position :]
            self.cursor_position = 0


def _looks_like_browser_pane(node: object) -> bool:
    """Return True for the browser pane without importing it at runtime."""
    required = (
        "highlighted_row_is_loadable",
        "action_load_xprompt",
        "scroll_preview_down",
        "scroll_preview_up",
        "_close_filter",
    )
    return all(callable(getattr(node, name, None)) for name in required)


__all__ = ["BrowserFilterInput"]
