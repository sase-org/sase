"""Failed stage for the New Project wizard."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from .new_project_progress import render_checklist
from .new_project_progress_model import ProgressView
from .new_project_rendering import clean_source_text


class NewProjectFailed(Vertical):
    """Failure stage with retry, terminal, and back-to-review actions."""

    can_focus = True
    BINDINGS = [
        ("r", "retry", "Retry"),
        ("t", "terminal", "Terminal"),
        ("b", "back", "Back"),
    ]

    class RetryRequested(Message):
        """Re-run the Review check with the same draft."""

    class TerminalRequested(Message):
        """Run the add argv in a suspended terminal, then re-plan."""

    class BackRequested(Message):
        """Return to Review with the last plan."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._view = ProgressView()
        self._message = ""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="new-project-failed-scroll"):
            yield Static(
                "COULD NOT FINISH",
                id="new-project-failed-heading",
                classes="new-project-card-heading",
            )
            yield Static("", id="new-project-failed-message", markup=False)
            yield Static("", id="new-project-failed-checklist", markup=False)

    def show_failure(self, view: ProgressView, *, message: str = "") -> None:
        """Paint the kept checklist and the terminal result message."""
        self._view = view
        self._message = message
        if self.is_mounted:
            self._paint()

    def action_retry(self) -> None:
        self.post_message(self.RetryRequested())

    def action_terminal(self) -> None:
        self.post_message(self.TerminalRequested())

    def action_back(self) -> None:
        self.post_message(self.BackRequested())

    def _paint(self) -> None:
        result = self._view.result
        message = clean_source_text(self._message or (result.message if result else ""))
        block = Text()
        if message:
            block.append(message, style="#FF5F5F")
        failed = next(
            (step for step in self._view.checklist() if step.state == "failed"),
            None,
        )
        if failed is not None and failed.hint:
            if message:
                block.append("\n")
            block.append(clean_source_text(failed.hint), style="#FFAF5F")
        self.query_one("#new-project-failed-message", Static).update(block)
        self.query_one("#new-project-failed-checklist", Static).update(
            render_checklist(self._view.checklist())
        )


__all__ = ["NewProjectFailed"]
