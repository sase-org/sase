"""Single-line :class:`VimTextArea` -- a vim/readline replacement for ``Input``.

``SingleLineVimTextArea`` gives a host the full vim + readline editing layer in
a widget that behaves like a Textual ``Input``: Enter submits (posting a
``Submitted`` message) instead of inserting a newline, and the document is kept
to a single line -- ``o`` / ``O`` / ``ctrl+j`` are suppressed and any newline in
inserted, pasted, or register text is flattened to a space. Hosts may enable
``soft_wrap`` to display that one logical line across multiple visual rows.
``Changed`` is the inherited ``TextArea.Changed`` message, so hosts keep their
event-driven validation flow with only the value read (prefer ``.text``;
``.value`` is a compatibility alias during the migration) changing.
"""

from __future__ import annotations

from typing import Any

from textual.events import Key
from textual.message import Message

from sase.ace.tui.widgets.vim_text_area import VimTextArea

__all__ = ["SingleLineVimTextArea"]

_UNSET = object()


class SingleLineVimTextArea(VimTextArea):
    """A one-document-line ``VimTextArea`` that submits on Enter.

    Adoption recipe for replacing a Textual ``Input``:

    - yield ``SingleLineVimTextArea`` and read ``.text`` instead of ``.value``;
    - handle ``on_single_line_vim_text_area_submitted`` instead of
      ``on_input_submitted``;
    - handle ``on_text_area_changed`` instead of ``on_input_changed``;
    - focus normally, then call ``_update_vim_mode_display()`` if the widget is
      mounted hidden or the host wants the border title primed immediately;
    - prefill positionally or via ``text`` / ``value``, move the cursor to the
      end, and use ``select_all()`` where type-to-replace is desired;
    - modal Escape bindings become two-stage: INSERT ``esc`` enters NORMAL,
      NORMAL ``esc`` bubbles to the modal cancel action;
    - leave ``tab_behavior`` at its default ``"focus"`` for multi-field forms.

    ``soft_wrap`` defaults to false, but hosts may enable it to grow or scroll
    over multiple display rows while preserving the single logical document
    line. Line start/end motions (``ctrl+a``, ``ctrl+e``, ``0``, and ``$``)
    remain logical-line based. In NORMAL mode, ``j`` and ``k`` follow Textual's
    wrap-aware navigator and therefore move between wrapped display rows.
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
        value = kwargs.pop("value", _UNSET)
        if value is not _UNSET:
            if args:
                raise TypeError(
                    "SingleLineVimTextArea accepts initial text positionally "
                    "or via value=, not both"
                )
            args = (value,)
        # Hosts may opt into soft wrapping; line numbers never make sense for
        # the single logical document line.
        kwargs.setdefault("soft_wrap", False)
        kwargs.setdefault("show_line_numbers", False)
        super().__init__(*args, **kwargs)
        self.show_line_numbers = False

    @property
    def value(self) -> str:
        """Compatibility alias for old ``Input`` callers; prefer ``.text``."""
        return self.text

    @value.setter
    def value(self, new_value: str) -> None:
        self.text = new_value

    @property
    def cursor_position(self) -> int:
        """Compatibility alias for the single-line cursor column."""
        return self.cursor_location[1]

    @cursor_position.setter
    def cursor_position(self, position: int) -> None:
        line_end = len(self.document.get_line(0))
        col = max(0, min(position, line_end))
        self.move_cursor((0, col))

    def action_select_all(self) -> None:
        """Compatibility action matching ``Input.action_select_all``."""
        self.select_all()

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
