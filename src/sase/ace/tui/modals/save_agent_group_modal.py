"""Modal for naming a saved dismissed-agent group."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


@dataclass(frozen=True)
class SaveAgentGroupResult:
    """Confirmed saved-group name result."""

    name: str | None


class _GroupNameInput(SingleLineVimTextArea):
    """Single-line vim editor for optional saved-group names."""


class SaveAgentGroupModal(ModalScreen[SaveAgentGroupResult | None]):
    """Prompt for an optional saved agent group name."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, candidate_count: int) -> None:
        super().__init__()
        self._candidate_count = candidate_count

    @property
    def candidate_count(self) -> int:
        """Number of marked agents that will be saved if confirmed."""

        return self._candidate_count

    def compose(self) -> ComposeResult:
        """Compose the save-agent-group modal."""

        with Container(id="save-agent-group-container"):
            yield Label("Save Agent Group", id="save-agent-group-title")
            yield Label(
                f"{self._candidate_count} {_agent_label(self._candidate_count)} marked",
                id="save-agent-group-context",
            )
            yield Label(
                "Enter a name, or leave blank to use the generated summary.",
                id="save-agent-group-hint",
            )
            yield _GroupNameInput(
                placeholder="Optional group name",
                id="save-agent-group-name-input",
            )

    def on_mount(self) -> None:
        """Focus the name input."""

        editor = self.query_one("#save-agent-group-name-input", _GroupNameInput)
        editor.focus()
        editor._update_vim_mode_display()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Submit a confirmed save result."""

        name = event.value.strip() or None
        self.dismiss(SaveAgentGroupResult(name=name))

    def action_cancel(self) -> None:
        """Cancel without saving."""

        self.dismiss(None)


def _agent_label(count: int) -> str:
    return "agent" if count == 1 else "agents"
