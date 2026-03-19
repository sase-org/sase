"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from textual.events import Key
from textual.strip import Strip
from textual.widgets import TextArea

from sase.ace.tui.widgets._vim_motions import (
    find_next_word_end,
    find_next_word_start,
    find_next_WORD_end,
    find_next_WORD_start,
    find_prev_word_start,
    find_prev_WORD_start,
)

if TYPE_CHECKING:
    from ..app import AceApp
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


def _prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextArea(TextArea):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt. Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    # Shared state: last cancelled prompt text (also accessed by PromptInputBar)
    _last_cancelled_prompt: str = ""

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

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or fill last cancelled prompt if empty."""
        if not self.text and PromptTextArea._last_cancelled_prompt:
            self.text = PromptTextArea._last_cancelled_prompt
            doc = self.document
            last_line = doc.line_count - 1
            last_col = len(doc.get_line(last_line))
            self.cursor_location = (last_line, last_col)
        else:
            super().action_cursor_line_end(select)

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._vim_mode = "normal"
        self.read_only = True
        self.show_line_numbers = True
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = "Prompt [NORMAL]"
            bar.border_subtitle = "[Esc] cancel  [i] insert"

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._vim_mode = "insert"
        self.read_only = False
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = "Prompt"
            cancelled = PromptTextArea._last_cancelled_prompt
            if cancelled:
                hint = cancelled[:40] + "…" if len(cancelled) > 40 else cancelled
                bar.border_subtitle = f"[^E] {hint}"
            else:
                bar.border_subtitle = "[Esc] cancel"

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

        # Handle pending key sequences (gg)
        if self._pending_keys:
            pending = self._pending_keys
            self._pending_keys = ""
            if pending == "g" and key == "g":
                self.cursor_location = (0, 0)
            return True

        # Escape - cancel prompt bar
        if event.key == "escape":
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return True

        # Basic movement
        if key == "h":
            self.action_cursor_left()
            return True
        if key == "j":
            self.action_cursor_down()
            return True
        if key == "k":
            self.action_cursor_up()
            return True
        if key == "l":
            self.action_cursor_right()
            return True

        # Word movement
        doc = self.document
        if key == "w":
            self.cursor_location = find_next_word_start(doc, *self.cursor_location)
            return True
        if key == "W":
            self.cursor_location = find_next_WORD_start(doc, *self.cursor_location)
            return True
        if key == "b":
            self.cursor_location = find_prev_word_start(doc, *self.cursor_location)
            return True
        if key == "B":
            self.cursor_location = find_prev_WORD_start(doc, *self.cursor_location)
            return True
        if key == "e":
            self.cursor_location = find_next_word_end(doc, *self.cursor_location)
            return True
        if key == "E":
            self.cursor_location = find_next_WORD_end(doc, *self.cursor_location)
            return True

        # Line movement
        if key == "0":
            row = self.cursor_location[0]
            self.cursor_location = (row, 0)
            return True
        if key == "$":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self.cursor_location = (row, len(line))
            return True
        if key == "^":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            col = 0
            while col < len(line) and line[col].isspace():
                col += 1
            self.cursor_location = (row, col)
            return True

        # Document movement
        if key == "g":
            self._pending_keys = "g"
            return True
        if key == "G":
            last_row = self.document.line_count - 1
            self.cursor_location = (last_row, 0)
            return True

        # Mode switching
        if key == "i":
            self._enter_insert_mode()
            return True
        if key == "a":
            row, col = self.cursor_location
            line = self.document.get_line(row)
            self._enter_insert_mode()
            if col < len(line):
                self.cursor_location = (row, col + 1)
            return True
        if key == "A":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            return True
        if key == "I":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            col = 0
            while col < len(line) and line[col].isspace():
                col += 1
            self._enter_insert_mode()
            self.cursor_location = (row, col)
            return True
        if key == "o":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return True
        if key == "O":
            row = self.cursor_location[0]
            self._enter_insert_mode()
            self.cursor_location = (row, 0)
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            self.cursor_location = (row, 0)
            return True

        # Unhandled key - let it through for arrow keys, etc.
        return False

    def render_line(self, y: int) -> Strip:
        """Bypass cache in NORMAL mode so relative line numbers stay current."""
        if self._vim_mode == "normal" and self.show_line_numbers:
            return self._render_line(y)
        if self._vim_mode != "normal" and self.show_line_numbers:
            return self._render_insert_line(y)
        return super().render_line(y)

    def _render_insert_line(self, y: int) -> Strip:
        """Color absolute line numbers in INSERT mode with cyan (#3AA99F)."""
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        _line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        gutter_style = (self._theme.gutter_style or Style.null()) + Style(
            color="#3AA99F"
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = Segment(segments[0].text, gutter_style)
            return Strip(segments, strip.cell_length)

        return strip

    def _render_line(self, y: int) -> Strip:
        """Show relative line numbers in NORMAL mode."""
        strip = super()._render_line(y)
        if self._vim_mode != "normal" or not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        cursor_row = self.cursor_location[0]
        if line_index == cursor_row:
            gutter_content = str(line_index + 1)
        else:
            gutter_content = str(abs(line_index - cursor_row))

        gutter_width = self.gutter_width
        gutter_width_no_margin = gutter_width - 2

        theme = self._theme
        if line_index == cursor_row:
            base = (
                (theme.cursor_line_gutter_style or Style.null())
                if self.highlight_cursor_line
                else Style.null()
            )
            gutter_style = base + Style(color="#D0A215", bold=True)
        elif line_index < cursor_row:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#4385BE")
        else:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#8B7EC8")

        new_gutter = Segment(
            f"{gutter_content:>{gutter_width_no_margin}}  ", gutter_style
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = new_gutter
            return Strip(segments, strip.cell_length)

        return strip

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
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Detect '##' trigger before the second '#' is inserted
        if event.character == "#":
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
