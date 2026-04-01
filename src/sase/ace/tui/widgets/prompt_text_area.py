"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

import asyncio
import difflib
import os
import re
from typing import TYPE_CHECKING, Any

from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import TextArea

from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets.file_completion import extract_path_token, list_completions

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    from ..app import AceApp


def _prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextArea(VimNormalModeMixin, LineRenderingMixin, TextArea):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt. Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    BINDINGS = [
        ("enter", "submit_prompt", "Submit"),
        ("ctrl+j", "insert_newline", "New line"),
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+g", "open_editor", "Edit in editor"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._vim_mode: str = "insert"
        self._pending_keys: str = ""
        self._count_prefix: str = ""
        self._pending_count: int | None = None
        self._pending_operator: str = ""
        self._pending_operator_count: int = 1
        self._mutation_key_buffer: list[str] = []
        self._last_mutation_keys: list[str] = []
        self._replaying_dot: bool = False
        self._last_char_search: tuple[str, str] | None = None
        self._formatting: bool = False
        self._snippet_tabstops: list[int] = []
        self._snippet_end_from_doc_end: int = 0

    @property
    def _ace_app(self) -> AceApp:
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app

    def _find_prompt_bar(self) -> Any:
        """Walk up the widget tree to find the parent PromptInputBar."""
        PromptInputBar = _prompt_bar_class()
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                return parent
            parent = parent.parent
        return None

    def action_submit_prompt(self) -> None:
        """Submit the prompt text."""
        self._snippet_tabstops = []
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

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

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or end of next line if already there."""
        row, col = self.cursor_location
        line_end = len(self.document.get_line(row))
        if col >= line_end and row < self.document.line_count - 1:
            next_end = len(self.document.get_line(row + 1))
            self.move_cursor((row + 1, next_end), select=select)
        else:
            super().action_cursor_line_end(select=select)

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Move to start of line, or start of previous line if already there."""
        row, col = self.cursor_location
        if col == 0 and row > 0:
            self.move_cursor((row - 1, 0), select=select)
        else:
            super().action_cursor_line_start(select=select)

    def action_open_editor(self) -> None:
        """Request to open external editor."""
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            row, col = self.cursor_location
            bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        bar = self._find_prompt_bar()
        if bar and bar._mode == "feedback":
            return
        PromptInputBar = _prompt_bar_class()
        if bar:
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def _get_snippets(self) -> dict[str, str]:
        """Get the snippet registry from the app config."""
        return self._ace_app._snippets

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

        # Replace trigger word with expanded text
        self._replace_via_keyboard(expanded, (row, word_start), (row, col))

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

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._vim_mode = "normal"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._snippet_tabstops = []
        self.read_only = True
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar._dismiss_file_completion()
            bar.border_title = f"{bar._base_title} [NORMAL]"
            bar.border_subtitle = "[Esc] cancel  [i] insert"

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self.read_only = False
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = bar._base_title
            bar.border_subtitle = "[Esc] cancel"

    async def _handle_file_completion_key(self, event: Key) -> bool:
        """Handle key events for file completion dropdown.

        Returns True if the key was consumed by dropdown navigation.
        """
        bar = self._find_prompt_bar()
        if not bar or not bar._file_dropdown:
            return False

        dropdown = bar._file_dropdown
        if event.key in ("down", "tab"):
            event.stop()
            event.prevent_default()
            dropdown.move_down()
            return True
        if event.key in ("up", "shift+tab"):
            event.stop()
            event.prevent_default()
            dropdown.move_up()
            return True
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            await self._accept_file_completion()
            return True
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            bar._dismiss_file_completion()
            return True
        return False

    async def _check_file_completion(self) -> None:
        """Check if cursor is in a path context and show/update/dismiss dropdown."""
        bar = self._find_prompt_bar()
        if not bar:
            return

        row, col = self.cursor_location
        line = self.document.get_line(row)
        result = extract_path_token(line, col)

        if result is None:
            bar._dismiss_file_completion()
            return

        _, token = result
        entries = list_completions(token, os.getcwd())

        if not entries:
            bar._dismiss_file_completion()
            return

        # Path display: the directory being listed
        if token.endswith("/"):
            path_display = token
        elif "/" in token:
            path_display = token[: token.rfind("/") + 1]
        else:
            path_display = ""

        await bar._show_file_completion(entries, path_display)

    async def _accept_file_completion(self) -> None:
        """Accept the selected completion entry."""
        bar = self._find_prompt_bar()
        if not bar or not bar._file_dropdown:
            return

        entry = bar._file_dropdown.selected_entry
        if not entry:
            return

        row, col = self.cursor_location
        line = self.document.get_line(row)
        result = extract_path_token(line, col)
        if not result:
            bar._dismiss_file_completion()
            return

        token_start, token = result

        # Compute replacement: directory prefix + selected entry name
        if "/" in token:
            dir_prefix = token[: token.rfind("/") + 1]
        else:
            dir_prefix = ""

        if entry.is_dir:
            replacement = dir_prefix + entry.name + "/"
        else:
            replacement = dir_prefix + entry.name

        self._replace_via_keyboard(replacement, (row, token_start), (row, col))

        if entry.is_dir:
            # Drill-down: show completions for the new directory
            await self._check_file_completion()
        else:
            bar._dismiss_file_completion()

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        # File completion dropdown navigation (must come before all other handlers)
        if await self._handle_file_completion_key(event):
            return

        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_submit_prompt()
            return

        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Tab in INSERT mode: expand snippet or advance tabstop (never insert literal tab)
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            if self._try_expand_snippet():
                return
            self._try_advance_tabstop()
            return

        # Detect '#@' trigger before the '@' is inserted (skip in feedback mode)
        if event.character == "@":
            bar = self._find_prompt_bar()
            if bar and bar._mode != "feedback":
                row, col = self.cursor_location
                if col > 0:
                    line = self.document.get_line(row)
                    if line[col - 1] == "#":
                        PromptInputBar = _prompt_bar_class()
                        bar.post_message(PromptInputBar.SnippetRequested())
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # File completion: check/update after any text or cursor change
        if self._vim_mode == "insert":
            await self._check_file_completion()

        # Auto-wrap: reflow with prettier when line exceeds available width.
        # Skip wrapping on space so the user's trailing space is never consumed
        # by the line break — wrapping will fire on the next non-space character
        # when the space has become an interior word separator.
        if (
            self._vim_mode == "insert"
            and event.character
            and event.character.isprintable()
            and event.character != " "
        ):
            await self._format_with_prettier()

    def on_blur(self) -> None:
        """Schedule a deferred refocus when the text area loses focus."""
        self.call_later(self._refocus_if_needed)

    def _refocus_if_needed(self) -> None:
        """Refocus this text area unless a modal is active."""
        if self.is_mounted and not isinstance(self.app.screen, ModalScreen):
            self.focus()
