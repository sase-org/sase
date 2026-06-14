"""Confirmation modal for reverting a done agent's commits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label

if TYPE_CHECKING:
    from sase.ace.revert_agent import RevertCommit, RevertPreview

# How many commit rows to show before collapsing the remainder into a count.
_MAX_COMMIT_ROWS = 10
_MAX_SDD_PATHS = 6


class ConfirmRevertAgentModal(ModalScreen[bool]):
    """Confirm reverting the commits associated with a selected agent."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, preview: RevertPreview) -> None:
        super().__init__()
        self._preview = preview

    def compose(self) -> ComposeResult:
        preview = self._preview
        count = preview.commit_count
        scope_word = "family" if preview.scope == "family" else "agent"

        with Container():
            yield Label("Revert Agent Commits", id="modal-title")
            yield Label(
                f"Agent: {preview.agent_name}  (scope: {scope_word})",
                id="revert-scope",
            )
            yield Label(
                f"{count} commit(s) will be reverted:",
                id="revert-count",
            )
            yield Label(self._commit_lines(), id="revert-commits")
            yield Label(self._sdd_summary(), id="revert-sdd")
            yield Label(
                "This creates a single revert commit (and pushes when a "
                "remote/branch is available).",
                id="revert-warning",
            )
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="cancel-btn", variant="primary")

    def _commit_lines(self) -> str:
        commits: tuple[RevertCommit, ...] = self._preview.commits
        shown = commits[:_MAX_COMMIT_ROWS]
        lines = [f"{commit.sha}  {commit.subject}" for commit in shown]
        remaining = len(commits) - len(shown)
        if remaining > 0:
            lines.append(f"... and {remaining} more")
        return "\n".join(lines)

    def _sdd_summary(self) -> str:
        sdd_paths = self._preview.sdd_paths
        if not sdd_paths:
            return "SDD files: (none)"
        shown = sdd_paths[:_MAX_SDD_PATHS]
        summary = ", ".join(shown)
        remaining = len(sdd_paths) - len(shown)
        if remaining > 0:
            summary += f", +{remaining} more"
        return f"SDD files: {summary}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
