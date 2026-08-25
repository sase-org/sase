"""Create one typed artifact link from a marked row to the current row."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select


@dataclass(frozen=True, slots=True)
class ArtifactLinkRelationChoice:
    """One relation the manual artifact-link action may write."""

    slug: str
    label: str


@dataclass(frozen=True, slots=True)
class ArtifactLinkResult:
    """Validated fields returned by :class:`ArtifactLinkModal`."""

    relation: str
    reason: str


class ArtifactLinkModal(ModalScreen[ArtifactLinkResult | None]):
    """Collect a writable relation and required reason for one artifact link."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Link")]

    def __init__(
        self,
        *,
        source_label: str,
        target_label: str,
        relations: tuple[ArtifactLinkRelationChoice, ...],
    ) -> None:
        super().__init__()
        self._source_label = source_label
        self._target_label = target_label
        self._relations = relations

    def compose(self) -> ComposeResult:
        first = self._relations[0].slug if self._relations else ""
        with Container(id="artifact-link-container", classes="bead-modal-container"):
            yield Label("Link artifacts", classes="bead-modal-title")
            yield Label("Source", classes="bead-modal-label")
            yield Label(self._source_label, id="artifact-link-source")
            yield Label("Target", classes="bead-modal-label")
            yield Label(self._target_label, id="artifact-link-target")
            yield Label("Relation", classes="bead-modal-label")
            yield Select(
                [(choice.label, choice.slug) for choice in self._relations],
                value=first,
                allow_blank=False,
                id="artifact-link-relation",
            )
            yield Label("Reason", classes="bead-modal-label")
            yield Input(id="artifact-link-reason")
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Link  Ctrl+S", id="artifact-link-save", variant="primary")
                yield Button("Cancel  Esc", id="artifact-link-cancel")

    def on_mount(self) -> None:
        self.query_one("#artifact-link-reason", Input).focus()

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "artifact-link-save":
            self.action_save()
        else:
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "artifact-link-reason":
            self.action_save()

    def action_save(self) -> None:
        relation = str(self.query_one("#artifact-link-relation", Select).value or "")
        reason = self.query_one("#artifact-link-reason", Input).value.strip()
        if not relation:
            self.notify("Artifact link relation is required", severity="error")
            self.query_one("#artifact-link-relation", Select).focus()
            return
        if not reason:
            self.notify("Artifact link reason is required", severity="error")
            self.query_one("#artifact-link-reason", Input).focus()
            return
        self.dismiss(ArtifactLinkResult(relation=relation, reason=reason))

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "ArtifactLinkModal",
    "ArtifactLinkRelationChoice",
    "ArtifactLinkResult",
]
