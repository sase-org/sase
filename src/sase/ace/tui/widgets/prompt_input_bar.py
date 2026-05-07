"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    append_input_hints,
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
        self._completion_visible = False
        self._completion_line_count = 0

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        if self._mode == "feedback":
            return "Plan Feedback"
        if self._mode == "approve_prompt":
            return "Coder Prompt"
        return "Prompt"

    def compose(self) -> ComposeResult:
        """Compose the input bar layout."""
        if self._mode == "feedback":
            placeholder = "Type plan feedback...  [^G] editor  [^J] newline"
        elif self._mode == "approve_prompt":
            placeholder = "Type coder prompt...  [^G] editor  [^J] newline"
        else:
            placeholder = (
                "Type prompt, '.' for history, '#@' for snippets  "
                "[^T] path complete  [^G] editor  [^Y] workflow  [^J] newline"
            )
        yield Static("", id="prompt-completion", classes="hidden")
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
        if self._mode in ("feedback", "approve_prompt"):
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
        # +2 for border top and bottom, plus completion panel when visible
        completion_rows = self._completion_line_count if self._completion_visible else 0
        new_height = min(max(visual_lines + 2 + completion_rows, 3), max_height)
        self.styles.height = new_height

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._update_height()

    def show_file_completions(
        self,
        token: str,
        rows: list[CompletionCandidate],
        selected_index: int,
        scroll_offset: int = 0,
        completion_kind: str = "file",
    ) -> None:
        """Show the path/xprompt completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: "file" for path completion, "xprompt" for xprompt.
        """
        panel = self.query_one("#prompt-completion", Static)
        total = len(rows)
        visible = rows[scroll_offset : scroll_offset + MAX_VISIBLE]

        is_xprompt = completion_kind == "xprompt"
        is_history = completion_kind == "file_history"
        content = Text()
        for i, candidate in enumerate(visible):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected_index

            if is_selected:
                content.append("\u25b8 ", style="bold")
            else:
                content.append("  ")

            if is_xprompt:
                self._append_xprompt_completion_row(content, candidate, is_selected)
            elif candidate.is_dir:
                content.append("\U0001f4c1 ")
                content.append(
                    candidate.display, style="bold cyan" if is_selected else "cyan"
                )
            else:
                content.append("\U0001f4c4 ")
                content.append(candidate.display, style="bold" if is_selected else "")

            if i < len(visible) - 1:
                content.append("\n")

        remaining = total - (scroll_offset + len(visible))
        if remaining > 0:
            content.append(f"\n  \u2193 {remaining} more\u2026", style="dim")

        # Border title: "xprompts" for xprompt completion, "recent files"
        # for file-history completion, directory for file.
        if is_xprompt:
            panel.border_title = "xprompts"
        elif is_history:
            panel.border_title = "recent files"
        elif "/" in token:
            panel.border_title = token[: token.rindex("/") + 1]
        else:
            panel.border_title = token

        if is_history:
            panel.border_subtitle = "[^L] accept  [^D] delete"
        else:
            panel.border_subtitle = ""

        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3  # +3 for panel border + margin
        self._update_height()

    def _append_xprompt_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one xprompt completion row using assist metadata when present."""
        content.append(
            candidate.display,
            style="bold green" if is_selected else "green",
        )
        entry = (
            candidate.metadata
            if isinstance(candidate.metadata, XPromptAssistEntry)
            else None
        )
        if entry is None:
            return

        content.append(f"  {entry.kind}", style="dim")
        append_input_hints(content, entry.inputs)

    def hide_file_completions(self) -> None:
        """Hide the path completion panel."""
        panel = self.query_one("#prompt-completion", Static)
        panel.update("")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_line_count = 0
        self._update_height()

    def show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Show the post-accept xprompt argument hint panel."""
        panel = self.query_one("#prompt-completion", Static)
        content = Text()
        content.append(hint.reference_text, style="bold green")
        content.append(" arguments", style="dim")
        append_input_hints(
            content,
            hint.entry.inputs,
            active_index=hint.active_input_index,
        )

        panel.border_title = "xprompt args"
        panel.border_subtitle = "[:] colon  [(] named args"
        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3
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
        text_area._clear_xprompt_arg_hint()
        stripped = text_area.text.strip()
        self.post_message(self.Cancelled(cancelled_text=stripped, mode=self._mode))

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
