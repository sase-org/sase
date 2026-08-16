"""Create-bead modal."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, TextArea

from sase.bead.model import FlagRecord, IssueType, PhaseSize


@dataclass(frozen=True)
class BeadCreateResult:
    title: str
    description: str
    size: str
    ready: bool
    issue_type: str = IssueType.TASK.value
    flag_key: str = ""
    flag_remove_by_date: str = ""
    flag_remove_by_release: str = ""


class BeadCreateModal(ModalScreen[BeadCreateResult | None]):
    """Collect the fields valid for a standalone task or flag bead."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Create")]

    def __init__(self, project_name: str) -> None:
        super().__init__()
        self.project_name = project_name

    def compose(self) -> ComposeResult:
        with Container(id="bead-create-container", classes="bead-modal-container"):
            yield Label(
                f"Create bead · {self.project_name}",
                classes="bead-modal-title",
            )
            yield Label("Type", classes="bead-modal-label")
            yield Select(
                [
                    ("Task", IssueType.TASK.value),
                    ("Flag", IssueType.FLAG.value),
                ],
                value=IssueType.TASK.value,
                allow_blank=False,
                id="bead-create-type",
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
            yield Label("Flag key", classes="bead-modal-label")
            yield Input(id="bead-create-flag-key")
            yield Label("Remove by date", classes="bead-modal-label")
            yield Input(placeholder="YYYY-MM-DD", id="bead-create-flag-date")
            yield Label("Remove by release", classes="bead-modal-label")
            yield Input(placeholder="0.19.0", id="bead-create-flag-release")
            yield Checkbox("Ready for triage", id="bead-create-ready")
            with Horizontal(classes="bead-modal-buttons"):
                yield Button(
                    "Create  Ctrl+S",
                    id="bead-create-save",
                    variant="primary",
                )
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
            self.notify("Bead title cannot be empty", severity="error")
            return
        issue_type = str(self.query_one("#bead-create-type", Select).value)
        size = ""
        flag = None
        ready = self.query_one("#bead-create-ready", Checkbox).value
        if issue_type == IssueType.FLAG.value:
            flag = self._flag_record()
            if flag is None:
                return
            ready = False
        else:
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
                ready=ready,
                issue_type=issue_type,
                flag_key="" if flag is None else flag.key,
                flag_remove_by_date="" if flag is None else flag.remove_by_date,
                flag_remove_by_release=("" if flag is None else flag.remove_by_release),
            )
        )

    def _flag_record(self) -> FlagRecord | None:
        key = self.query_one("#bead-create-flag-key", Input).value.strip()
        remove_by_date = self.query_one("#bead-create-flag-date", Input).value.strip()
        remove_by_release = self.query_one(
            "#bead-create-flag-release", Input
        ).value.strip()
        record = FlagRecord(
            key=key,
            remove_by_date=remove_by_date,
            remove_by_release=remove_by_release,
        )
        try:
            record.validate()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            target = (
                "#bead-create-flag-key"
                if not key
                else "#bead-create-flag-date"
                if not remove_by_date
                else "#bead-create-flag-release"
            )
            self.query_one(target, Input).focus()
            return None
        return record

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadCreateModal", "BeadCreateResult"]
