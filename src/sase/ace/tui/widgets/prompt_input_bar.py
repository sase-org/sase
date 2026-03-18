"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from textual.app import ComposeResult
from textual.events import Key
from textual.message import Message
from textual.strip import Strip
from textual.widgets import Static, TextArea

if TYPE_CHECKING:
    from ..app import AceApp


class _PromptTextArea(TextArea):
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

    @property
    def _ace_app(self) -> "AceApp":
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app

    def _find_prompt_bar(self) -> "PromptInputBar | None":
        """Walk up the widget tree to find the parent PromptInputBar."""
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
        bar = self._find_prompt_bar()
        if bar:
            row, col = self.cursor_location
            bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        bar = self._find_prompt_bar()
        if bar:
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or fill last cancelled prompt if empty."""
        if not self.text and PromptInputBar._last_cancelled_prompt:
            self.text = PromptInputBar._last_cancelled_prompt
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
            cancelled = PromptInputBar._last_cancelled_prompt
            if cancelled:
                hint = cancelled[:40] + "…" if len(cancelled) > 40 else cancelled
                bar.border_subtitle = f"[^E] {hint}"
            else:
                bar.border_subtitle = "[Esc] cancel"

    def render_line(self, y: int) -> Strip:
        """Bypass cache in NORMAL mode so relative line numbers stay current."""
        if self._vim_mode == "normal" and self.show_line_numbers:
            return self._render_line(y)
        return super().render_line(y)

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
        if cursor_row == line_index and self.highlight_cursor_line:
            gutter_style = theme.cursor_line_gutter_style
        else:
            gutter_style = theme.gutter_style

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
            if event.key == "escape":
                event.stop()
                event.prevent_default()
                bar = self._find_prompt_bar()
                if bar:
                    bar.action_cancel()
                return
            if event.character == "i":
                event.stop()
                event.prevent_default()
                self._enter_insert_mode()
                return
            # In NORMAL mode, let arrow keys work via BINDINGS;
            # read_only=True prevents character insertion.
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Detect '##' trigger before the second '#' is inserted
        if event.character == "#":
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


class PromptInputBar(Static):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    _last_cancelled_prompt: str = ""

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        pass

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
        """Message sent when user requests snippet modal ('##')."""

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
            "Type prompt, '.' for history, '##' for snippets  "
            "[^G] editor  [^Y] workflow  [^J] newline"
        )
        yield _PromptTextArea(
            self._initial_value,
            show_line_numbers=False,
            highlight_cursor_line=False,
            id="prompt-input",
            placeholder=placeholder,
        )

    def on_mount(self) -> None:
        """Focus the TextArea on mount and position cursor at end."""
        text_area = self.query_one("#prompt-input", _PromptTextArea)
        text_area.focus()
        if self._initial_value:
            doc = text_area.document
            last_line = doc.line_count - 1
            last_col = len(doc.get_line(last_line))
            text_area.cursor_location = (last_line, last_col)

        # Border title and subtitle
        self.border_title = "Prompt"
        cancelled = PromptInputBar._last_cancelled_prompt
        if cancelled:
            hint = cancelled[:40] + "…" if len(cancelled) > 40 else cancelled
            self.border_subtitle = f"[^E] {hint}"
        else:
            self.border_subtitle = "[Esc] cancel"

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes."""
        text_area = self.query_one("#prompt-input", _PromptTextArea)
        if text_area._vim_mode == "insert":
            text_area.show_line_numbers = text_area.document.line_count > 1
        self._update_height()

    def _get_visual_line_count(self) -> int:
        """Count visual lines accounting for soft wrap."""
        try:
            text_area = self.query_one("#prompt-input", _PromptTextArea)
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
        text_area = self.query_one("#prompt-input", _PromptTextArea)
        if text_area.text.strip():
            PromptInputBar._last_cancelled_prompt = text_area.text
        self.post_message(self.Cancelled())

    def insert_snippet(self, snippet_name: str) -> None:
        """Insert a snippet reference at the cursor position.

        The first '#' from the '##' trigger is already in the input
        (second '#' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
        """
        text_area = self.query_one("#prompt-input", _PromptTextArea)
        start, end = text_area.selection
        text_area._replace_via_keyboard(snippet_name, start, end)
        text_area.focus()
