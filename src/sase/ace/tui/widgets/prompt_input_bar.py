"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptInputBar(Static):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        def __init__(self, cancelled_text: str = "") -> None:
            super().__init__()
            self.cancelled_text = cancelled_text

    class EditorRequested(Message):
        """Message sent when user requests external editor (Ctrl+G)."""

        def __init__(
            self,
            current_text: str = "",
            cursor_row: int = 0,
            cursor_col: int = 0,
        ) -> None:
            super().__init__()
            self.current_text = current_text
            self.cursor_row = cursor_row
            self.cursor_col = cursor_col

    class HistoryRequested(Message):
        """Message sent when user requests prompt history picker ('.')."""

        def __init__(self, vcs_prefix: str = "") -> None:
            super().__init__()
            self.vcs_prefix = vcs_prefix

    class SnippetRequested(Message):
        """Message sent when user requests snippet modal ('#@')."""

        pass

    class WorkflowEditorRequested(Message):
        """Message sent when user requests workflow YAML editor (Ctrl+Y)."""

        pass

    BINDINGS = []  # type: ignore[assignment]

    def __init__(self, initial_value: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        """Compose the input bar layout."""
        placeholder = (
            "Type prompt, '.' for history, '#@' for snippets  "
            "[^G] editor  [^Y] workflow  [^J] newline"
        )
        yield PromptTextArea(
            self._initial_value,
            show_line_numbers=False,
            highlight_cursor_line=False,
            id="prompt-input",
            placeholder=placeholder,
        )

    def on_mount(self) -> None:
        """Focus the TextArea on mount and position cursor at end."""
        text_area = self.query_one("#prompt-input", PromptTextArea)
        text_area.focus()
        if self._initial_value:
            doc = text_area.document
            last_line = doc.line_count - 1
            last_col = len(doc.get_line(last_line))
            text_area.cursor_location = (last_line, last_col)

        # Border title and subtitle
        self.border_title = "Prompt"
        self.border_subtitle = "[Esc] cancel"

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes."""
        text_area = self.query_one("#prompt-input", PromptTextArea)
        if text_area._vim_mode == "insert":
            text_area.show_line_numbers = text_area.document.line_count > 1
        self._update_height()

    def _get_visual_line_count(self) -> int:
        """Count visual lines accounting for soft wrap."""
        try:
            text_area = self.query_one("#prompt-input", PromptTextArea)
        except Exception:
            return 1

        doc = text_area.document
        text_width = text_area.size.width

        # Subtract gutter width when line numbers are shown
        if text_area.show_line_numbers:
            gutter_width = len(str(doc.line_count)) + 2
            text_width -= gutter_width

        if text_width <= 0:
            return doc.line_count

        visual_lines = 0
        for i in range(doc.line_count):
            line = doc.get_line(i)
            line_len = len(line)
            if line_len <= text_width:
                visual_lines += 1
            else:
                visual_lines += -(-line_len // text_width)  # ceil division

        return max(1, visual_lines)

    def _update_height(self) -> None:
        """Auto-grow the bar based on content, up to the full screen height."""
        visual_lines = self._get_visual_line_count()
        # Reserve a few rows for the header/tabs at minimum
        screen_height = self.screen.size.height if self.screen else 50
        max_height = screen_height - 2
        # +2 for border top and bottom
        new_height = min(max(visual_lines + 2, 3), max_height)
        self.styles.height = new_height

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._update_height()

    def _handle_text_submission(self, text: str) -> None:
        """Process text submission from the TextArea."""
        value = text.strip()

        # Check for '.' - trigger history picker
        if value == ".":
            self.post_message(self.HistoryRequested())
            return

        # Check for VCS dot-prompt (e.g., "#gh:sase ." or "#git:repo .")
        if value.endswith(" .") and value[0] == "#":
            vcs_prefix = value[:-2].rstrip()
            self.post_message(self.HistoryRequested(vcs_prefix=vcs_prefix))
            return

        # Normal submission
        self.post_message(self.Submitted(value))

    def action_cancel(self) -> None:
        """Cancel the input bar."""
        text_area = self.query_one("#prompt-input", PromptTextArea)
        stripped = text_area.text.strip()
        self.post_message(self.Cancelled(cancelled_text=stripped))

    def insert_snippet(self, snippet_name: str) -> None:
        """Insert a snippet reference at the cursor position.

        The '#' from the '#@' trigger is already in the input
        ('@' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
        """
        text_area = self.query_one("#prompt-input", PromptTextArea)
        start, end = text_area.selection
        text_area._replace_via_keyboard(snippet_name, start, end)
        text_area.focus()
