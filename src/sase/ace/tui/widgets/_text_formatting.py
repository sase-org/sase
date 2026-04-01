"""Text wrapping and formatting mixin for PromptTextArea."""

from __future__ import annotations

import asyncio
import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class TextFormattingMixin(_MixinBase):
    """Mixin providing text wrapping and prettier-based formatting.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _formatting: bool

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

    # -- Mixin implementation --

    def _get_wrap_width(self) -> int:
        """Get the width at which to auto-wrap text.

        Matches the Textual TextArea's internal ``wrap_width`` property
        which accounts for the gutter, scrollbar, and a 1-cell cursor
        reservation.
        """
        text_width = self.size.width
        if text_width <= 0:
            return 0
        # Reserve space for the gutter that will appear after wrapping
        gutter_width = len(str(max(self.document.line_count, 2))) + 2
        # Reserve space for the vertical scrollbar that overlays content
        scrollbar_width = self.styles.scrollbar_size_vertical
        # Reserve 1 cell for the cursor, matching TextArea.wrap_width
        cursor_width = 1
        return max(text_width - gutter_width - scrollbar_width - cursor_width, 1)

    def _auto_wrap_line(self) -> None:
        """Insert a newline when the cursor's line exceeds available width.

        Breaks at the last space at or before the wrap boundary so words
        are never split.  Falls back to a hard break only when there is
        no space to break on.
        """
        wrap_width = self._get_wrap_width()
        if wrap_width <= 0:
            return

        row, col = self.cursor_location
        line = self.document.get_line(row)

        if len(line) <= wrap_width:
            return

        # Find the last space at or before the wrap boundary
        break_pos = line.rfind(" ", 0, wrap_width + 1)

        if break_pos > 0:
            # Replace the space with a newline (consumes the space)
            self._replace_via_keyboard("\n", (row, break_pos), (row, break_pos + 1))
            if col > break_pos:
                self.cursor_location = (row + 1, col - break_pos - 1)
            else:
                self.cursor_location = (row, col)
        else:
            # No suitable space — hard break at the wrap boundary
            self._replace_via_keyboard("\n", (row, wrap_width), (row, wrap_width))
            if col >= wrap_width:
                self.cursor_location = (row + 1, col - wrap_width)
            else:
                self.cursor_location = (row, col)

    @staticmethod
    def _map_offset(old_text: str, new_text: str, old_offset: int) -> int:
        """Map a character offset from *old_text* into *new_text* using diff opcodes.

        Walks the ``difflib.SequenceMatcher`` opcodes to find where
        *old_offset* lands in the new text:

        - ``equal``: preserve relative position within the matching block.
        - ``delete`` / ``replace``: clamp to the start of the new-side range.
        - ``insert``: does not consume old characters; continue scanning.
        """
        matcher = difflib.SequenceMatcher(None, old_text, new_text)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                if old_offset <= i2:
                    return j1 + (old_offset - i1)
            elif tag in ("delete", "replace"):
                if old_offset <= i2:
                    return min(j1 + max(old_offset - i1, 0), j2)
            # 'insert' doesn't consume old chars — just advance new pointer
        return len(new_text)

    async def _format_with_prettier(self) -> None:
        """Reflow prompt text using prettier when a line overflows.

        Runs the full prompt through ``prettier --prose-wrap always`` to
        produce balanced paragraph wrapping.  Falls back to the simple
        ``_auto_wrap_line`` when prettier is unavailable or fails.
        """
        if self._formatting:
            return

        wrap_width = self._get_wrap_width()
        if wrap_width <= 0:
            return

        # Only format when at least one line actually overflows
        needs_format = any(
            len(self.document.get_line(i)) > wrap_width
            for i in range(self.document.line_count)
        )
        if not needs_format:
            return

        text = self.text
        row, col = self.cursor_location

        # Absolute cursor offset so we can restore position after reflow
        cursor_offset = (
            sum(len(self.document.get_line(i)) + 1 for i in range(row)) + col
        )

        self._formatting = True
        try:
            proc = await asyncio.create_subprocess_exec(
                "prettier",
                "--parser",
                "markdown",
                "--prose-wrap",
                "always",
                "--print-width",
                str(wrap_width),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate(text.encode())

            if proc.returncode != 0:
                self._auto_wrap_line()
                return

            formatted = stdout.decode()
            # Prettier always appends a trailing newline
            if formatted.endswith("\n"):
                formatted = formatted[:-1]

            if formatted == text:
                return

            # If the user typed more while prettier was running, skip
            if self.text != text:
                return

            # Compute cursor mapping off the event loop (CPU-bound O(n^2) diff)
            loop = asyncio.get_running_loop()
            mapped = await loop.run_in_executor(
                None, self._map_offset, text, formatted, cursor_offset
            )

            # Re-check stale input since we yielded control to the event loop
            if self.text != text:
                return

            # Replace entire content with the reflowed version
            doc = self.document
            last_row = doc.line_count - 1
            last_col = len(doc.get_line(last_row))
            self._replace_via_keyboard(formatted, (0, 0), (last_row, last_col))

            # Restore cursor using diff-based offset mapping
            offset = min(mapped, len(formatted))
            remaining = offset
            lines = formatted.split("\n")
            new_row, new_col = len(lines) - 1, len(lines[-1])
            for i, line in enumerate(lines):
                if remaining <= len(line):
                    new_row = i
                    new_col = remaining
                    break
                remaining -= len(line) + 1
            self.cursor_location = (new_row, new_col)
        except FileNotFoundError:
            # prettier not installed — fall back to simple wrap
            self._auto_wrap_line()
        finally:
            self._formatting = False
