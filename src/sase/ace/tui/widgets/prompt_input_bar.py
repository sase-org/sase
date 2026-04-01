"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.file_completion import (
    CompletionEntry,
    FileCompletionDropdown,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptInputBar(Static):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str, mode: str = "prompt") -> None:
            super().__init__()
            self.value = value
            self.mode = mode

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        def __init__(self, cancelled_text: str = "", mode: str = "prompt") -> None:
            super().__init__()
            self.cancelled_text = cancelled_text
            self.mode = mode

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

        def __init__(self, vcs_prefix: str = "", show_cancelled: bool = False) -> None:
            super().__init__()
            self.vcs_prefix = vcs_prefix
            self.show_cancelled = show_cancelled

    class SnippetRequested(Message):
        """Message sent when user requests snippet modal ('#@')."""

        pass

    class WorkflowEditorRequested(Message):
        """Message sent when user requests workflow YAML editor (Ctrl+Y)."""

        pass

    BINDINGS = []  # type: ignore[assignment]

    def __init__(
        self, initial_value: str = "", mode: str = "prompt", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value
        self._mode = mode
        self._file_dropdown: FileCompletionDropdown | None = None

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        return "Plan Feedback" if self._mode == "feedback" else "Prompt"

    def compose(self) -> ComposeResult:
        """Compose the input bar layout."""
        if self._mode == "feedback":
            placeholder = "Type plan feedback...  [^G] editor  [^J] newline"
        else:
            placeholder = (
                "Type prompt, '.' for history, '#@' for snippets  "
                "[^G] editor  [^Y] workflow  [^J] newline"
            )
        yield PromptTextArea(
            self._initial_value,
            language="markdown",
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
        self.border_title = self._base_title
        if self._mode == "feedback":
            self.border_subtitle = "[Enter] send  [Esc] cancel"
            self.add_class("feedback-mode")
        else:
            self.border_subtitle = "[Esc] cancel"

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes."""
        text_area = self.query_one("#prompt-input", PromptTextArea)
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

        dropdown_h = 0
        if self._file_dropdown and self._file_dropdown.is_mounted:
            dropdown_h = self._file_dropdown.dropdown_height()

        # +2 for border top and bottom
        new_height = min(max(visual_lines + 2 + dropdown_h, 3), max_height)
        self.styles.height = new_height

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._update_height()

    def _handle_text_submission(self, text: str) -> None:
        """Process text submission from the TextArea."""
        value = text.strip()

        if self._mode != "feedback":
            # Check for '.' or '.x' - trigger history picker
            if value in (".", ".x"):
                self.post_message(self.HistoryRequested(show_cancelled=value == ".x"))
                return

            # Check for VCS dot-prompt (e.g., "#gh:sase ." or "#git:repo .x")
            if value.endswith((" .", " .x")) and value[0] == "#":
                show_cancelled = value.endswith(" .x")
                vcs_prefix = value.rsplit(" ", 1)[0].rstrip()
                self.post_message(
                    self.HistoryRequested(
                        vcs_prefix=vcs_prefix, show_cancelled=show_cancelled
                    )
                )
                return

        # Normal submission
        self.post_message(self.Submitted(value, mode=self._mode))

    def action_cancel(self) -> None:
        """Cancel the input bar."""
        text_area = self.query_one("#prompt-input", PromptTextArea)
        stripped = text_area.text.strip()
        self.post_message(self.Cancelled(cancelled_text=stripped, mode=self._mode))

    async def _show_file_completion(
        self,
        entries: list[CompletionEntry],
        path_display: str,
    ) -> None:
        """Show or update the file completion dropdown."""
        if self._file_dropdown is None:
            self._file_dropdown = FileCompletionDropdown(entries, path_display)
            text_area = self.query_one("#prompt-input")
            await self.mount(self._file_dropdown, before=text_area)
        else:
            self._file_dropdown.update_entries(entries, path_display)
        self._update_height()

    def _dismiss_file_completion(self) -> None:
        """Dismiss and remove the file completion dropdown."""
        if self._file_dropdown is not None:
            if self._file_dropdown.is_mounted:
                self._file_dropdown.remove()
            self._file_dropdown = None
            self._update_height()

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
