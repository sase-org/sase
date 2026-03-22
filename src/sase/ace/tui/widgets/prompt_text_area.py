"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.events import Key
from textual.widgets import TextArea

from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin

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
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

    def _get_wrap_width(self) -> int:
        """Get the width at which to auto-wrap text.

        Always accounts for the gutter since line numbers appear when
        line_count > 1 (which will be the case after wrapping).  Also
        reserves space for the vertical scrollbar which overlays the
        content area when visible.
        """
        text_width = self.size.width
        if text_width <= 0:
            return 0
        # Reserve space for the gutter that will appear after wrapping
        gutter_width = len(str(max(self.document.line_count, 2))) + 2
        # Reserve space for the vertical scrollbar that overlays content
        scrollbar_width = self.styles.scrollbar_size_vertical
        return max(text_width - gutter_width - scrollbar_width, 1)

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

            # Replace entire content with the reflowed version
            doc = self.document
            last_row = doc.line_count - 1
            last_col = len(doc.get_line(last_row))
            self._replace_via_keyboard(formatted, (0, 0), (last_row, last_col))

            # Restore cursor to the equivalent position
            offset = min(cursor_offset, len(formatted))
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
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._vim_mode = "normal"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self.read_only = True
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = "Prompt [NORMAL]"
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
            bar.border_title = "Prompt"
            bar.border_subtitle = "[Esc] cancel"

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_submit_prompt()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
                await self._format_with_prettier()
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Detect '#@' trigger before the '@' is inserted
        if event.character == "@":
            PromptInputBar = _prompt_bar_class()
            row, col = self.cursor_location
            if col > 0:
                line = self.document.get_line(row)
                if line[col - 1] == "#":
                    bar = self._find_prompt_bar()
                    if bar:
                        bar.post_message(PromptInputBar.SnippetRequested())
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # Auto-wrap: reflow with prettier when line exceeds available width
        if (
            self._vim_mode == "insert"
            and event.character
            and event.character.isprintable()
        ):
            await self._format_with_prettier()
