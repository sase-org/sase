"""Create-task-bead modal."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, TextArea

from sase.bead.model import PhaseSize


@dataclass(frozen=True)
class BeadCreateResult:
    title: str
    description: str
    size: str
    ready: bool


class BeadCreateModal(ModalScreen[BeadCreateResult | None]):
    """Collect the fields valid for a standalone task bead."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Create")]

    def __init__(self, project_name: str) -> None:
        super().__init__()
        self.project_name = project_name

    def compose(self) -> ComposeResult:
        with Container(id="bead-create-container", classes="bead-modal-container"):
            yield Label(
                f"Create task bead · {self.project_name}", classes="bead-modal-title"
            )
            yield Label("Title", classes="bead-modal-label")
            yield Input(id="bead-create-title")
            yield Label("Description", classes="bead-modal-label")
            yield TextArea("", id="bead-create-description")
            yield Label("Size", classes="bead-modal-label")
            yield Select(
                [
                    ("Choose a size…", ""),
                    *[(size.value, size.value) for size in PhaseSize],
                ],
                value="",
                allow_blank=False,
                id="bead-create-size",
            )
            yield Checkbox("Ready for triage", id="bead-create-ready")
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Create  Ctrl+S", id="bead-create-save", variant="primary")
                yield Button("Cancel  Esc", id="bead-create-cancel")

    def on_mount(self) -> None:
        self.query_one("#bead-create-title", Input).focus()

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-create-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        title = self.query_one("#bead-create-title", Input).value.strip()
        if not title:
            self.notify("Task title cannot be empty", severity="error")
            return
        size = str(self.query_one("#bead-create-size", Select).value)
        if not size:
            self.notify("Task size is required", severity="error")
            self.query_one("#bead-create-size", Select).focus()
            return
        self.dismiss(
            BeadCreateResult(
                title=title,
                description=self.query_one(
                    "#bead-create-description", TextArea
                ).text.strip(),
                size=size,
                ready=self.query_one("#bead-create-ready", Checkbox).value,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadCreateModal", "BeadCreateResult"]
