"""Ask a reviewer how to retry a partially executed AND branch.

The executor refuses to silently re-run commands that already succeeded, so
the choice between resuming after the failed step and running the whole branch
again belongs to the reviewer. This modal is where they make it; nothing here
guesses.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

GateRetryChoice = Literal["resume", "restart"]


class GateRetryModal(ModalScreen["GateRetryChoice | None"]):
    """Present the resume-or-restart choice for one incomplete attempt."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("r", "resume", "Resume"),
        ("R", "restart", "Restart"),
    ]

    def __init__(
        self,
        *,
        completed_option_ids: tuple[str, ...],
        failed_option_ids: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._completed = completed_option_ids
        self._failed = failed_option_ids

    def compose(self) -> ComposeResult:
        with Container(id="gate-retry-container", classes="gate-retry-dialog"):
            yield Static(
                Text("Partly executed branch", style="bold yellow"),
                id="gate-retry-title",
            )
            yield Static(self._summary(), id="gate-retry-summary")
            with Horizontal(id="gate-retry-buttons"):
                yield Button(
                    "r Resume after the failed step",
                    id="gate-retry-resume",
                    variant="primary",
                )
                yield Button(
                    "R Run the whole branch again",
                    id="gate-retry-restart",
                    variant="warning",
                )

    def on_mount(self) -> None:
        self.query_one("#gate-retry-resume", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gate-retry-resume":
            self.action_resume()
        elif event.button.id == "gate-retry-restart":
            self.action_restart()

    def action_resume(self) -> None:
        self.dismiss("resume")

    def action_restart(self) -> None:
        self.dismiss("restart")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _summary(self) -> Text:
        text = Text()
        text.append("Completed: ", style="dim")
        text.append(", ".join(self._completed) or "none", style="green")
        text.append("\nFailed: ", style="dim")
        text.append(", ".join(self._failed) or "none", style="red")
        text.append(
            "\n\nResuming skips the completed commands. Restarting runs them again,"
            "\nwhich is safe only if they tolerate being re-run.",
            style="dim",
        )
        return text


__all__ = ["GateRetryChoice", "GateRetryModal"]
