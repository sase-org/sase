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
    """Custom input for the XPrompt browser with navigation key bindings.

    Since the filter input always has focus while the XPrompts tab is active,
    Ctrl-key combinations are used for navigation and actions to avoid conflicts
    with text input. Brackets remain ordinary filter text, while the Admin
    Center's priority ``Tab`` / ``Shift+Tab`` bindings handle main-tab
    navigation. The apostrophe key is likewise reserved: while the filter is
    empty it arms the adaptive entry-jump hints instead of being typed, and
    while jump mode is active every key is routed to the jump state machine
    first. Once the filter holds text, apostrophe falls through to normal
    :class:`Input` editing so quoted filter text can be typed.
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
        """Reserve empty-filter numeric tab keys and the jump key before they
        become text.

        While the filter is empty, digit keys are likewise reserved for the
        Admin Center's numbered tab keymaps: in-range digits jump to a tab and
        out-of-range digits are swallowed no-ops via the same modal action.
        Once the filter holds text, digits fall through to normal
        :class:`Input` editing so values such as ``bug2`` or ``2026`` can be
        typed. When this pane is nested in the Config hub, ``[`` / ``]``
        cycle Config sub-tabs instead of becoming filter text.

        The apostrophe key follows the same empty-filter reservation: with no
        filter text, it arms the pane's adaptive jump hints instead of being
        typed. While jump mode is active, every key -- hint characters,
        ``'`` itself for the back stack, and ``escape`` -- is routed to the
        jump state machine first, so none of it leaks into the filter text.

        ``Ctrl+I`` remains the explicit inline-load binding when the terminal
        reports it distinctly. A bare ``Tab`` always reaches the Admin Center's
        priority next-tab binding.
        """
        pane = self._pane()
        if pane is not None and pane.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if pane.handle_jump_key(key):
                event.stop()
                event.prevent_default()
            return

        from .config_hub_keys import handle_config_hub_bracket_key

        if handle_config_hub_bracket_key(self, event):
            return

        if event.key == "apostrophe" and not self.value and pane is not None:
            event.stop()
            event.prevent_default()
            pane.action_jump_to_entry()
            return

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
    )
    return all(callable(getattr(node, name, None)) for name in required)


__all__ = ["BrowserFilterInput"]
