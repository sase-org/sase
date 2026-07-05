"""One-line :class:`VimTextArea` -- a vim/readline replacement for ``Input``.

``SingleLineVimTextArea`` gives a host the full vim + readline editing layer in
a widget that behaves like a Textual ``Input``: Enter submits (posting a
``Submitted`` message) instead of inserting a newline, and the document is kept
to a single line -- ``o`` / ``O`` / ``ctrl+j`` are suppressed and any newline in
inserted, pasted, or register text is flattened to a space. ``Changed`` is the
inherited ``TextArea.Changed`` message, so hosts keep their event-driven
validation flow with only the value read (``.value`` -> ``.text``) changing.
"""

from __future__ import annotations

from typing import Any

from textual.events import Key
from textual.message import Message

from sase.ace.tui.widgets.vim_text_area import VimTextArea

__all__ = ["SingleLineVimTextArea"]


class SingleLineVimTextArea(VimTextArea):
    """A single-line ``VimTextArea`` that submits on Enter, like an ``Input``.

    Use :attr:`text` to read the value and listen for :class:`Submitted` (Enter)
    and ``TextArea.Changed`` (edits) to drive validation and submission.
    """

    class Submitted(Message):
        """Posted when Enter is pressed (mirrors ``Input.Submitted``)."""

        def __init__(self, text_area: SingleLineVimTextArea, value: str) -> None:
            super().__init__()
            self.text_area = text_area
            self.value = value

        @property
        def control(self) -> SingleLineVimTextArea:
            """The originating widget (for Textual ``@on`` routing)."""
            return self.text_area

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # A one-line box never soft-wraps or shows line numbers.
        kwargs.setdefault("soft_wrap", False)
        kwargs.setdefault("show_line_numbers", False)
        super().__init__(*args, **kwargs)
        self.show_line_numbers = False

    async def _on_key(self, event: Key) -> None:
        """Submit on Enter and swallow every newline-producing key.

        Only the newline-producing keys are consumed here; every other key is
        left for the base ``VimTextArea._on_key`` (reached next in Textual's MRO
        handler walk) so the full vim/readline layer still applies. Consuming a
        key with ``prevent_default`` also stops that walk.
        """
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        # ``ctrl+j`` (open newline) and NORMAL-mode ``o`` / ``O`` (open line
        # below / above) would grow the document past one line: suppress them.
        if event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
            return
        if self._vim_mode == "normal" and event.character in ("o", "O"):
            event.stop()
            event.prevent_default()
            return

    def _enter_normal_mode(self) -> None:
        """Enter NORMAL mode without the multi-line gutter / cursor-line noise."""
        super()._enter_normal_mode()
        self.show_line_numbers = False
        self.highlight_cursor_line = False

    def _replace_via_keyboard(
        self,
        insert: str,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> Any:
        """Flatten any newline before it can split the single-line document.

        Covers every mutation the vim tower routes through here -- linewise
        paste, bracketed paste, register content, dot-repeat -- so the invariant
        holds regardless of how the text arrived.
        """
        if "\n" in insert or "\r" in insert:
            insert = insert.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        return super()._replace_via_keyboard(insert, start, end)
