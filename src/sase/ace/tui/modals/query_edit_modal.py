"""Query edit modal for the ace TUI."""

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _QueryInput(SingleLineVimTextArea):
    """Single-line vim editor for search query strings."""


class QueryEditModal(ModalScreen[str | None]):
    """Modal for editing the search query."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        current_query: str,
        title: str = "Edit Search Query",
        *,
        hint: str | None = None,
        validator: Callable[[str], None] | None = None,
        initial_error: str | None = None,
    ) -> None:
        """Initialize the query edit modal.

        Args:
            current_query: The current query string
            title: The modal title text
            hint: Optional one-line cheatsheet shown under the input.
            validator: Optional callable invoked on Apply (or Enter) before
                dismissing. If it raises ``Exception``, the modal stays open
                and renders the exception message under the input. The
                modal dismisses cleanly only when the validator returns
                without raising (or when no validator is given).
            initial_error: Optional error message to render on first paint
                (e.g. the prior failed parse so the user sees what went
                wrong without having to re-Apply).
        """
        super().__init__()
        self.current_query = current_query
        self._title = title
        self._hint = hint
        self._validator = validator
        self._initial_error = initial_error

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label(self._title, id="modal-title")
            yield _QueryInput(value=self.current_query, id="query-input")
            if self._hint:
                yield Label(self._hint, id="query-hint")
            error_text = self._initial_error or ""
            error = Label(error_text, id="query-error")
            error.display = bool(error_text)
            yield error
            with Horizontal(id="button-row"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        """Focus the input on mount and move cursor to end (clears selection)."""
        query_input = self.query_one("#query-input", _QueryInput)
        query_input.focus()
        # Move cursor to end to clear the default selection
        query_input.cursor_position = len(query_input.text)
        query_input._update_vim_mode_display()

    def _try_apply(self, value: str) -> None:
        """Run the validator (if any) and dismiss on success."""
        if self._validator is None:
            self.dismiss(value)
            return
        try:
            self._validator(value)
        except Exception as exc:
            self._set_error(str(exc))
            return
        self.dismiss(value)

    def _set_error(self, message: str) -> None:
        try:
            error = self.query_one("#query-error", Label)
        except Exception:
            return
        error.update(message)
        error.display = bool(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "apply":
            query_input = self.query_one("#query-input", _QueryInput)
            self._try_apply(query_input.text)
        else:
            self.dismiss(None)

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Handle Enter key in input."""
        self._try_apply(event.value)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
