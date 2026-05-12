"""Filter input widget for the revive agent modal."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Input


class ReviveFilterInput(Input):
    """Custom input for revive modal with scroll key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
    ]

    def action_scroll_preview_down(self) -> None:
        """Scroll the preview panel down."""
        modal: Any = self.screen
        if hasattr(modal, "scroll_preview_down"):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        """Scroll preview up, or clear input if already at top."""
        modal: Any = self.screen
        if not hasattr(modal, "scroll_preview_up"):
            return
        scroll = modal.query_one("#dismissed-preview-scroll", VerticalScroll)
        if scroll.scroll_y > 0:
            modal.scroll_preview_up()
        elif self.cursor_position > 0:
            self.value = self.value[self.cursor_position :]
            self.cursor_position = 0
