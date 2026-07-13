"""Filter input widget for the XPrompt browser pane."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, cast

from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Input

if TYPE_CHECKING:
    from .xprompt_browser_pane import XPromptBrowserPane


class BrowserFilterInput(Input):
    """Custom input for the XPrompt browser with navigation key bindings.

    Since the filter input always has focus while the XPrompts tab is active,
    Ctrl-key combinations are used for navigation and actions to avoid conflicts
    with text input. Brackets remain ordinary filter text, while the Admin
    Center's priority ``Tab`` / ``Shift+Tab`` bindings handle main-tab
    navigation.
    """

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Prev"),
        ("enter", "forward('edit_xprompt')", "Edit here"),
        ("E", "forward('external_edit_xprompt')", "External editor"),
        ("ctrl+o", "forward('add_xprompt')", "Add"),
        ("ctrl+i", "forward('load_xprompt')", "Load"),
    ]

    def on_key(self, event: events.Key) -> None:
        """Reserve empty-filter numeric tab keys before they become text.

        While the filter is empty, digit keys are likewise reserved for the
        Admin Center's numbered tab keymaps: ``1``-``6`` jump to a tab and the
        out-of-range ``7``-``9``/``0`` are swallowed no-ops via the same modal
        action. Once the filter holds text, digits fall through to normal
        :class:`Input` editing so values such as ``bug2`` or ``2026`` can be
        typed.

        ``Ctrl+I`` remains the explicit inline-load binding when the terminal
        reports it distinctly. A bare ``Tab`` always reaches the Admin Center's
        priority next-tab binding.
        """
        if len(event.key) == 1 and event.key.isdigit() and not self.value:
            host = self.screen
            focus_tab = getattr(host, "action_focus_center_tab", None)
            if callable(focus_tab):
                event.stop()
                event.prevent_default()
                focus_tab(int(event.key))

    def _pane(self) -> XPromptBrowserPane | None:
        """Return the owning :class:`XPromptBrowserPane`, if any."""
        node: object | None = self.parent
        while node is not None:
            if _looks_like_browser_pane(node):
                return cast("XPromptBrowserPane", node)
            node = getattr(node, "parent", None)
        return None

    async def action_forward(self, action_name: str) -> None:
        """Forward an action to the owning pane."""
        pane = self._pane()
        if pane is not None:
            result = getattr(pane, f"action_{action_name}")()
            if inspect.isawaitable(result):
                await result

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
    )
    return all(callable(getattr(node, name, None)) for name in required)


__all__ = ["BrowserFilterInput"]
