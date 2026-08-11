"""Create/edit modal for provider-neutral tracker issues."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea

from sase.vcs_provider import IssueWire


@dataclass(frozen=True)
class IssueEditResult:
    """Validated fields returned by :class:`IssueEditModal`."""

    title: str
    body: str
    labels: tuple[str, ...]


class IssueEditModal(ModalScreen[IssueEditResult | None]):
    """Edit an issue title, markdown body, and comma-separated labels."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        issue: IssueWire | None = None,
        *,
        heading: str | None = None,
    ) -> None:
        super().__init__()
        self._issue = issue
        self._heading = heading

    def compose(self) -> ComposeResult:
        title = self._heading or (
            "Edit Issue" if self._issue is not None else "Create Issue"
        )
        issue = self._issue
        with Container(id="issue-edit-container"):
            yield Label(title, id="issue-edit-title")
            yield Label("Title", classes="issue-edit-label")
            yield Input(
                value=issue.title if issue is not None else "",
                placeholder="Concise issue title",
                id="issue-edit-title-input",
            )
            yield Label("Body (Markdown)", classes="issue-edit-label")
            yield TextArea(
                issue.body if issue is not None else "", id="issue-edit-body"
            )
            yield Label("Labels", classes="issue-edit-label")
            yield Input(
                value=", ".join(issue.labels) if issue is not None else "",
                placeholder="bug, priority:high",
                id="issue-edit-labels",
            )
            with Horizontal(id="issue-edit-buttons"):
                yield Button("Save  Ctrl+S", id="issue-edit-save", variant="primary")
                yield Button("Cancel  Esc", id="issue-edit-cancel")

    def on_mount(self) -> None:
        title = self.query_one("#issue-edit-title-input", Input)
        title.focus()
        if self._issue is not None:
            title.select_all()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "issue-edit-title-input":
            self.query_one("#issue-edit-body", TextArea).focus()
        else:
            self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "issue-edit-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        title = self.query_one("#issue-edit-title-input", Input).value.strip()
        if not title:
            self.notify("Issue title cannot be empty", severity="error")
            return
        body = self.query_one("#issue-edit-body", TextArea).text
        raw_labels = self.query_one("#issue-edit-labels", Input).value
        labels = tuple(
            dict.fromkeys(
                label.strip() for label in raw_labels.split(",") if label.strip()
            )
        )
        self.dismiss(IssueEditResult(title=title, body=body, labels=labels))

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["IssueEditModal", "IssueEditResult"]
