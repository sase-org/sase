"""Snippet expansion mixin for PromptTextArea."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from ..app import AceApp
else:
    _MixinBase = object


class SnippetExpansionMixin(_MixinBase):
    """Mixin providing snippet expansion and tabstop navigation.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _snippet_tabstops: list[int]
        _snippet_end_from_doc_end: int

        @property
        def _ace_app(self) -> AceApp: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

    # -- Mixin implementation --

    def _get_snippets(self) -> dict[str, str]:
        """Get the snippet registry from the app config."""
        return self._ace_app.get_snippets()

    def _try_expand_snippet(self) -> bool:
        """Try to expand a snippet trigger word at the cursor.

        Extracts the word immediately before the cursor, looks it up in the
        snippet registry, and replaces it with the expanded template.  Supports
        tabstop markers ``$1``, ``$2``, ... for sequential cursor positions and
        ``$0`` for the final cursor position.  If no ``$0`` is present, the
        final position defaults to the end of the expansion.

        Returns True if a snippet was expanded.
        """
        row, col = self.cursor_location
        line = self.document.get_line(row)

        # Extract word before cursor (alphanumeric + underscore)
        word_start = col
        while word_start > 0 and (
            line[word_start - 1].isalnum() or line[word_start - 1] == "_"
        ):
            word_start -= 1

        if word_start == col:
            return False  # No word before cursor

        trigger = line[word_start:col]
        snippets = self._get_snippets()

        if trigger not in snippets:
            return False

        template = snippets[trigger]
        return self._expand_snippet_template_at_range(
            template,
            (row, word_start),
            (row, col),
        )

    def _expand_snippet_template_at_range(
        self,
        template: str,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> bool:
        """Expand a snippet template at an explicit document range."""
        row, word_start = start
        line = self.document.get_line(row)

        # Find all tabstop markers ($0, $1, $2, ...) and build cleaned text
        markers: list[tuple[int, int]] = []  # (tabstop_number, offset_in_cleaned)
        cleaned_parts: list[str] = []
        last_end = 0
        cleaned_offset = 0
        seen: set[int] = set()

        for match in re.finditer(r"\$(\d+)", template):
            num = int(match.group(1))
            before = template[last_end : match.start()]
            cleaned_parts.append(before)
            cleaned_offset += len(before)
            if num not in seen:
                markers.append((num, cleaned_offset))
                seen.add(num)
            last_end = match.end()

        cleaned_parts.append(template[last_end:])
        expanded = "".join(cleaned_parts)

        # Indent continuation lines to match line indentation
        indent_len = len(line) - len(line.lstrip())
        indent = line[:indent_len]
        if "\n" in expanded and indent:
            pre_indent = expanded
            exp_lines = expanded.split("\n")
            expanded = exp_lines[0] + "".join(
                "\n" + indent + el for el in exp_lines[1:]
            )
            markers = [
                (num, offset + pre_indent[:offset].count("\n") * len(indent))
                for num, offset in markers
            ]

        # Replace target range with expanded text
        self._replace_via_keyboard(expanded, start, end)

        if not markers:
            # No markers — cursor stays at end (default behavior)
            self._snippet_tabstops = []
            return True

        # Add implicit $0 at end if not present
        if 0 not in seen:
            markers.append((0, len(expanded)))

        # Sort: $1, $2, ..., then $0 last
        markers.sort(key=lambda m: (m[0] == 0, m[0]))

        expansion_len = len(expanded)

        # Position cursor at first tabstop
        first_offset = markers[0][1]
        self._position_cursor_at_expansion_offset(
            row, word_start, expanded, first_offset
        )

        # Store remaining tabstops as chars-from-end-of-expansion
        self._snippet_tabstops = [expansion_len - offset for _, offset in markers[1:]]

        # Track expansion end for offset adjustment on advance
        doc_len = len(self.text)
        start_abs = (
            sum(len(self.document.get_line(r)) + 1 for r in range(row)) + word_start
        )
        self._snippet_end_from_doc_end = doc_len - (start_abs + expansion_len)

        return True

    def _position_cursor_at_expansion_offset(
        self,
        start_row: int,
        start_col: int,
        expanded: str,
        offset: int,
    ) -> None:
        """Position cursor at a character offset within expanded text."""
        text_before = expanded[:offset]
        lines = text_before.split("\n")
        if len(lines) > 1:
            self.cursor_location = (start_row + len(lines) - 1, len(lines[-1]))
        else:
            self.cursor_location = (start_row, start_col + len(lines[-1]))

    def _try_advance_tabstop(self) -> bool:
        """Advance to the next snippet tabstop. Returns True if advanced."""
        if not self._snippet_tabstops:
            return False

        from_end = self._snippet_tabstops.pop(0)
        doc_len = len(self.text)
        expansion_end = doc_len - self._snippet_end_from_doc_end
        target_offset = expansion_end - from_end

        # Convert absolute offset to (row, col)
        remaining = target_offset
        for r in range(self.document.line_count):
            line_len = len(self.document.get_line(r))
            if remaining <= line_len:
                self.cursor_location = (r, remaining)
                return True
            remaining -= line_len + 1

        # Fallback: end of document
        last_row = self.document.line_count - 1
        self.cursor_location = (last_row, len(self.document.get_line(last_row)))
        return True
