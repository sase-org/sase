"""Command Line input widget: a single-line vim field with an implicit prefix.

The ``❯ sase `` prefix is dim and non-editable — the ``sase`` prefix is
implicit — and a leading ``sase `` the user types or pastes is stripped at
once. Escape follows the panel rules: INSERT with an empty line hides the
panel, otherwise the field drops to NORMAL mode. ``;`` on an empty line hops
to the Command Palette.
"""

from __future__ import annotations

from typing import Any

from textual.events import Key

from sase.ace.tui.command_line.session import strip_implicit_prefix
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

#: Dim, non-editable prefix rendered before the editable text.
COMMAND_LINE_PREFIX = "❯ sase "


class CommandLineInput(SingleLineVimTextArea):
    """Single-line vim input for the Command Line panel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "command-line-input")
        super().__init__(*args, **kwargs)

    def normalized_text(self) -> str:
        """Return the editable text with any typed ``sase `` prefix stripped."""
        return strip_implicit_prefix(self.text)

    def set_line(self, line: str) -> None:
        """Replace the line and move the cursor to the end."""
        self.text = strip_implicit_prefix(line)
        try:
            self.move_cursor((0, len(self.document.get_line(0))))
        except Exception:  # noqa: BLE001 - cursor restore is best effort.
            pass

    async def _on_key(self, event: Key) -> None:
        """Apply the panel's Escape and ``;``-hop rules before vim handling."""
        if event.key == "escape" and self._vim_mode == "insert":
            if not self.text.strip():
                event.stop()
                event.prevent_default()
                await self.screen.dismiss(None)
                return
        if event.key == "semicolon" and self._vim_mode == "insert":
            if not self.text.strip():
                hop = getattr(self.screen, "hop_to_palette", None)
                if callable(hop):
                    event.stop()
                    event.prevent_default()
                    await hop()
                    return
        await super()._on_key(event)
