"""Field-driven editor for bead metadata."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.bead_type_presentation import bead_type_presentation
from sase.task_type_presentation import task_type_presentation
from sase.task_types import issue_task_type_slug


@dataclass(frozen=True, init=False)
class BeadEditorResult:
    """Validated editable values returned by :class:`BeadEditorModal`."""

    title: str
    description: str
    notes: str
    status: str
    assignee: str
    owner: str
    model: str
    size: str | None
    design: str
    patch_name: str | None
    patch_bug_id: str | None

    def __init__(
        self,
        *,
        title: str,
        description: str,
        notes: str,
        status: str,
        assignee: str,
        owner: str,
        model: str,
        size: str | None,
        design: str,
        patch_name: str | None = None,
        patch_bug_id: str | None = None,
        changespec_name: str | None = None,  # legacy compatibility alias
        changespec_bug_id: str | None = None,  # legacy compatibility alias
    ) -> None:
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "assignee", assignee)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "design", design)
        object.__setattr__(
            self,
            "patch_name",
            patch_name if patch_name is not None else changespec_name,
        )
        object.__setattr__(
            self,
            "patch_bug_id",
            patch_bug_id if patch_bug_id is not None else changespec_bug_id,
        )

    def changed_fields(self, issue: Issue) -> dict[str, str | None]:
        """Return only values that differ from *issue*."""
        candidates: dict[str, str | None] = {
            "title": self.title,
            "description": self.description,
            "notes": self.notes,
            "status": self.status,
            "assignee": self.assignee,
            "owner": self.owner,
            "model": self.model,
            "design": self.design,
        }
        current: dict[str, str | None] = {
            "title": issue.title,
            "description": issue.description,
            "notes": issue.notes_text,
            "status": issue.status.value,
            "assignee": issue.assignee,
            "owner": issue.owner,
            "model": issue.model,
            "design": issue.design,
        }
        if issue.issue_type is not IssueType.PLAN:
            candidates["size"] = self.size
            current["size"] = issue.size.value if issue.size is not None else None
        if issue.issue_type is IssueType.PLAN:
            candidates["patch_name"] = self.patch_name
            candidates["patch_bug_id"] = self.patch_bug_id
            current["patch_name"] = issue.patch_name or None
            current["patch_bug_id"] = issue.patch_bug_id or None
        return {
            key: value for key, value in candidates.items() if current[key] != value
        }


class BeadEditorModal(ModalScreen[BeadEditorResult | None]):
    """Edit only fields valid for the selected bead's type."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, issue: Issue) -> None:
        super().__init__()
        self.issue = issue

    def compose(self) -> ComposeResult:
        issue = self.issue
        presentation = bead_type_presentation(issue.issue_type)
        with Container(id="bead-editor-container", classes="bead-modal-container"):
            yield Label(
                f"Edit {presentation.glyph} {presentation.label} {issue.id}",
                classes="bead-modal-title",
            )
            with VerticalScroll(classes="bead-modal-fields"):
                yield from self._text_field("Title", "title", issue.title)
                yield Label("Description", classes="bead-modal-label")
                yield TextArea(issue.description, id="bead-editor-description")
                yield Label("Notes", classes="bead-modal-label")
                yield TextArea(issue.notes_text, id="bead-editor-notes")
                statuses = [Status.OPEN, Status.IN_PROGRESS, Status.CLOSED]
                if issue.issue_type is IssueType.TASK:
                    statuses.insert(1, Status.READY)
                if issue.status is Status.CLAIMED:
                    statuses.insert(1, Status.CLAIMED)
                yield Label("Status", classes="bead-modal-label")
                yield Select(
                    [(status.value, status.value) for status in statuses],
                    value=(
                        issue.status.value
                        if issue.status in statuses
                        else Status.IN_PROGRESS.value
                    ),
                    allow_blank=False,
                    id="bead-editor-status",
                )
                yield from self._text_field("Assignee", "assignee", issue.assignee)
                yield from self._text_field("Owner", "owner", issue.owner)
                yield from self._text_field("Model", "model", issue.model)
                if issue.issue_type is IssueType.TASK:
                    task_presentation = task_type_presentation(issue.task_type)
                    task_type_slug = issue_task_type_slug(issue.task_type)
                    yield Label("Task type (immutable)", classes="bead-modal-label")
                    yield Label(
                        Text(
                            f"{task_presentation.glyph} {task_type_slug}",
                            style=task_presentation.rich_style,
                        ),
                        classes="bead-modal-readonly-value",
                    )
                if issue.issue_type is not IssueType.PLAN:
                    yield Label("Size", classes="bead-modal-label")
                    yield Select(
                        [
                            ("None", ""),
                            *[(size.value, size.value) for size in PhaseSize],
                        ],
                        value=issue.size.value if issue.size is not None else "",
                        allow_blank=False,
                        id="bead-editor-size",
                    )
                yield from self._text_field("Design", "design", issue.design)
                if issue.issue_type is IssueType.PLAN:
                    yield from self._text_field(
                        "Patch name", "patch-name", issue.patch_name
                    )
                    yield from self._text_field(
                        "Bug id", "patch-bug-id", issue.patch_bug_id
                    )
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Save  Ctrl+S", id="bead-editor-save", variant="primary")
                yield Button("Cancel  Esc", id="bead-editor-cancel")

    @staticmethod
    def _text_field(label: str, field: str, value: str) -> ComposeResult:
        yield Label(label, classes="bead-modal-label")
        yield Input(value=value, id=f"bead-editor-{field}")

    def on_mount(self) -> None:
        self.query_one("#bead-editor-title", Input).focus()

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-editor-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        title = self._input("title").strip()
        if not title:
            self.notify("Bead title cannot be empty", severity="error")
            self.query_one("#bead-editor-title", Input).focus()
            return
        issue = self.issue
        size: str | None = None
        if issue.issue_type is not IssueType.PLAN:
            raw_size = self.query_one("#bead-editor-size", Select).value
            size = str(raw_size) or None
        patch_name: str | None = None
        patch_bug_id: str | None = None
        if issue.issue_type is IssueType.PLAN:
            patch_name = self._input("patch-name") or None
            patch_bug_id = self._input("patch-bug-id") or None
            if patch_bug_id and not patch_name:
                self.notify("Bug id requires a Patch name", severity="error")
                return
        self.dismiss(
            BeadEditorResult(
                title=title,
                description=self.query_one("#bead-editor-description", TextArea).text,
                notes=self.query_one("#bead-editor-notes", TextArea).text,
                status=str(self.query_one("#bead-editor-status", Select).value),
                assignee=self._input("assignee"),
                owner=self._input("owner"),
                model=self._input("model"),
                size=size,
                design=self._input("design"),
                patch_name=patch_name,
                patch_bug_id=patch_bug_id,
            )
        )

    def _input(self, field: str) -> str:
        return self.query_one(f"#bead-editor-{field}", Input).value.strip()

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadEditorModal", "BeadEditorResult"]
