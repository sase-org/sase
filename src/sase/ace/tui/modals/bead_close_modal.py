"""Close-with-reason modal for beads."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from sase.bead.model import Issue, IssueType, Resolution


@dataclass(frozen=True)
class BeadCloseResult:
    resolution: str
    reason: str
    note: str | None
    force: bool


class BeadCloseModal(ModalScreen[BeadCloseResult | None]):
    """Collect the full close contract and preview blocking descendants."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Close")]

    def __init__(
        self,
        issue: Issue,
        *,
        unclosed_descendants: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.issue = issue
        self.unclosed_descendants = unclosed_descendants

    def compose(self) -> ComposeResult:
        descendants = self.unclosed_descendants
        with Container(id="bead-close-container", classes="bead-modal-container"):
            yield Label(f"Close bead · {self.issue.id}", classes="bead-modal-title")
            if descendants:
                yield Static(
                    "Unclosed descendants (normal close will be rejected):\n"
                    + "\n".join(f"• {bead_id}" for bead_id in descendants),
                    id="bead-close-descendants",
                    classes="bead-modal-warning",
                )
            if self.issue.issue_type is IssueType.PLAN:
                yield Static(
                    "Warning: this epic may have active phase or land agents.",
                    classes="bead-modal-warning",
                )
            elif self.issue.issue_type is IssueType.PHASE and (
                self.issue.assignee or self.issue.status.value == "in_progress"
            ):
                yield Static(
                    "Warning: an agent may currently be working this phase.",
                    classes="bead-modal-warning",
                )
            yield Label("Resolution", classes="bead-modal-label")
            yield Select(
                [(resolution.value, resolution.value) for resolution in Resolution],
                value=Resolution.DONE.value,
                allow_blank=False,
                id="bead-close-resolution",
            )
            yield Label("Reason (required)", classes="bead-modal-label")
            yield Input(id="bead-close-reason")
            yield Label("Optional note", classes="bead-modal-label")
            yield TextArea("", id="bead-close-note")
            yield Checkbox(
                "Force-close all unclosed descendants",
                id="bead-close-force",
                disabled=not bool(descendants),
            )
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Close  Ctrl+S", id="bead-close-save", variant="error")
                yield Button("Cancel  Esc", id="bead-close-cancel")

    def on_mount(self) -> None:
        self.query_one("#bead-close-reason", Input).focus()

    @on(Checkbox.Changed, "#bead-close-force")
    def _on_force_changed(self, event: Checkbox.Changed) -> None:
        if event.value:
            resolution = self.query_one("#bead-close-resolution", Select)
            if resolution.value == Resolution.DONE.value:
                resolution.value = Resolution.CANCELED.value

    @on(Select.Changed, "#bead-close-resolution")
    def _on_resolution_changed(self, event: Select.Changed) -> None:
        force = self.query_one("#bead-close-force", Checkbox)
        if force.value and event.value == Resolution.DONE.value:
            self.query_one(
                "#bead-close-resolution", Select
            ).value = Resolution.CANCELED.value

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-close-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        reason = self.query_one("#bead-close-reason", Input).value.strip()
        if not reason:
            self.notify("Closing a bead requires a reason", severity="error")
            return
        force = self.query_one("#bead-close-force", Checkbox).value
        resolution = str(self.query_one("#bead-close-resolution", Select).value)
        if force and resolution == Resolution.DONE.value:
            self.notify(
                "A forced close requires a non-done resolution", severity="error"
            )
            return
        note = self.query_one("#bead-close-note", TextArea).text.strip() or None
        self.dismiss(BeadCloseResult(resolution, reason, note, force))

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadCloseModal", "BeadCloseResult"]
