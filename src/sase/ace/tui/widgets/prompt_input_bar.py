"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message
from textual.suggester import Suggester
from textual.widgets import Input, Label, Static

if TYPE_CHECKING:
    from ..app import AceApp


class _SingleSuggester(Suggester):
    """Suggester that returns a single fixed suggestion."""

    def __init__(self, suggestion: str) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._suggestion = suggestion

    async def get_suggestion(self, value: str) -> str | None:
        if self._suggestion.startswith(value):
            return self._suggestion
        return None


class _PromptInput(Input):
    """Custom Input with readline-style key bindings and special handlers."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+g", "open_editor", "Edit in editor"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
        ("ctrl+u", "unix_line_discard", "Clear to start"),
        ("ctrl+e", "end_or_fill_placeholder", "End/Fill"),
    ]

    @property
    def _ace_app(self) -> "AceApp":
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app

    def action_unix_line_discard(self) -> None:
        """Clear from cursor to beginning of line."""
        if self.cursor_position > 0:
            self.value = self.value[self.cursor_position :]
            self.cursor_position = 0

    def action_open_editor(self) -> None:
        """Request to open external editor."""
        # Find parent PromptInputBar and post message
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                parent.post_message(
                    PromptInputBar.EditorRequested(self.value, self.cursor_position)
                )
                return
            parent = parent.parent

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                parent.post_message(PromptInputBar.WorkflowEditorRequested())
                return
            parent = parent.parent

    def action_end_or_fill_placeholder(self) -> None:
        """Accept suggestion if available, otherwise move cursor to end."""
        if self._suggestion:
            self.value = self._suggestion
            self.cursor_position = len(self.value)
        else:
            self.action_end()

    def on_key(self, event: Key) -> None:
        """Handle key events for special triggers like '##' for snippets."""
        if event.character == "#":
            # Check if the character before cursor is also '#' (making '##')
            if self.cursor_position > 0 and self.value[self.cursor_position - 1] == "#":
                # Find parent PromptInputBar and post message
                parent = self.parent
                while parent is not None:
                    if isinstance(parent, PromptInputBar):
                        parent.post_message(PromptInputBar.SnippetRequested())
                        # Prevent the second '#' from being typed
                        event.prevent_default()
                        return
                    parent = parent.parent


class PromptInputBar(Static):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    _last_cancelled_prompt: str = ""

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str) -> None:
            """Initialize the message.

            Args:
                value: The prompt value
            """
            super().__init__()
            self.value = value

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        pass

    class EditorRequested(Message):
        """Message sent when user requests external editor (Ctrl+G)."""

        def __init__(self, current_text: str = "", cursor_position: int = 0) -> None:
            """Initialize the message.

            Args:
                current_text: The current text in the input field.
                cursor_position: The cursor column offset (0-indexed).
            """
            super().__init__()
            self.current_text = current_text
            self.cursor_position = cursor_position

    class HistoryRequested(Message):
        """Message sent when user requests prompt history picker ('.')."""

        def __init__(self, vcs_prefix: str = "") -> None:
            """Initialize the message.

            Args:
                vcs_prefix: VCS workflow prefix (e.g., "#gh:sase") to prepend
                    to the selected prompt. Empty string for plain dot-prompt.
            """
            super().__init__()
            self.vcs_prefix = vcs_prefix

    class SnippetRequested(Message):
        """Message sent when user requests snippet modal ('##')."""

        pass

    class WorkflowEditorRequested(Message):
        """Message sent when user requests workflow YAML editor (Ctrl+Y)."""

        pass

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, initial_value: str = "", **kwargs: Any) -> None:
        """Initialize the prompt input bar.

        Args:
            initial_value: Pre-populated text for the input field.
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        """Compose the input bar layout."""
        cancelled = PromptInputBar._last_cancelled_prompt
        placeholder = (
            "Type prompt, '.' for history, '##' for snippets [^G] editor [^Y] workflow"
        )
        suggester = _SingleSuggester(cancelled) if cancelled else None
        with Horizontal(id="prompt-input-container"):
            yield Label("Prompt: ", id="prompt-label")
            yield _PromptInput(
                placeholder=placeholder,
                suggester=suggester,
                id="prompt-input",
                value=self._initial_value,
                select_on_focus=not self._initial_value,
            )
            yield Label("[Esc] cancel", id="prompt-escape-hint", classes="dim-label")

    def on_mount(self) -> None:
        """Focus the input on mount and position cursor at end of initial text."""
        prompt_input = self.query_one("#prompt-input", _PromptInput)
        prompt_input.focus()
        if self._initial_value:
            prompt_input.cursor_position = len(self._initial_value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        value = event.value.strip()

        # Check for '.' - trigger history picker
        if value == ".":
            self.post_message(self.HistoryRequested())
            return

        # Check for VCS dot-prompt (e.g., "#gh:sase ." or "#git:repo .")
        # The '#' prefix indicates a workflow reference; trailing " ." means
        # the user wants to pick from prompt history for that VCS context.
        if value.endswith(" .") and value[0] == "#":
            vcs_prefix = value[:-2].rstrip()
            self.post_message(self.HistoryRequested(vcs_prefix=vcs_prefix))
            return

        # Normal submission
        self.post_message(self.Submitted(value))

    def action_cancel(self) -> None:
        """Cancel the input bar."""
        prompt_input = self.query_one("#prompt-input", _PromptInput)
        if prompt_input.value.strip():
            PromptInputBar._last_cancelled_prompt = prompt_input.value
        self.post_message(self.Cancelled())

    def insert_snippet(self, snippet_name: str) -> None:
        """Insert a snippet reference at the cursor position.

        The first '#' from the '##' trigger is already in the input
        (second '#' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
        """
        prompt_input = self.query_one("#prompt-input", _PromptInput)
        current_value = prompt_input.value
        cursor_pos = prompt_input.cursor_position
        new_value = (
            current_value[:cursor_pos] + snippet_name + current_value[cursor_pos:]
        )
        prompt_input.value = new_value
        prompt_input.cursor_position = cursor_pos + len(snippet_name)
        prompt_input.focus()
