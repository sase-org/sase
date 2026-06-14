"""Confirmation modal for reverting agent commits (single or bulk)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from sase.ace.revert_agent import BulkRevertPreview

if TYPE_CHECKING:
    from sase.ace.revert_agent import RevertCommit, RevertPreview

# How many commit rows to show before collapsing the remainder into a count.
_MAX_COMMIT_ROWS = 10
_MAX_SDD_PATHS = 6
# How many skipped (no-match) target names to list before collapsing.
_MAX_SKIPPED_TARGETS = 6


class ConfirmRevertAgentModal(ModalScreen[bool]):
    """Confirm reverting agent commits.

    Renders either a single-agent :class:`RevertPreview` or a multi-agent
    :class:`BulkRevertPreview`. Bulk mode shows the marked-agent count, the
    deduplicated newest-first combined commit set, any skipped (no-match)
    targets, and warns that all marked agents are reverted in one commit that
    rolls back as a unit on failure.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, preview: RevertPreview | BulkRevertPreview) -> None:
        super().__init__()
        self._preview = preview
        self._is_bulk = isinstance(preview, BulkRevertPreview)

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Revert Agent Commits", id="modal-title")
            if self._is_bulk:
                yield from self._compose_bulk()
            else:
                yield from self._compose_single()
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="cancel-btn", variant="primary")

    def _compose_single(self) -> ComposeResult:
        preview = self._preview
        assert not isinstance(preview, BulkRevertPreview)
        scope_word = "family" if preview.scope == "family" else "agent"
        yield Label(
            f"Agent: {preview.agent_name}  (scope: {scope_word})",
            id="revert-scope",
        )
        yield Label(
            f"{preview.commit_count} commit(s) will be reverted:",
            id="revert-count",
        )
        yield Label(self._commit_lines(), id="revert-commits")
        yield Label(self._sdd_summary(), id="revert-sdd")
        yield Label(
            "This creates a single revert commit (and pushes when a "
            "remote/branch is available).",
            id="revert-warning",
        )

    def _compose_bulk(self) -> ComposeResult:
        preview = self._preview
        assert isinstance(preview, BulkRevertPreview)
        yield Label(
            f"{preview.target_count} marked agent(s)  "
            f"(workspace: {preview.workspace_dir})",
            id="revert-scope",
        )
        yield Label(
            f"{preview.commit_count} commit(s) will be reverted:",
            id="revert-count",
        )
        yield Label(self._commit_lines(), id="revert-commits")
        yield Label(self._sdd_summary(), id="revert-sdd")
        yield Label(self._skipped_summary(), id="revert-skipped")
        yield Label(
            "This reverts all marked agents in a single commit and rolls back "
            "the whole operation on failure (pushes when a remote is available).",
            id="revert-warning",
        )

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

    def _skipped_summary(self) -> str:
        preview = self._preview
        assert isinstance(preview, BulkRevertPreview)
        skipped = preview.skipped_target_names
        if not skipped:
            return "Skipped (no commits): (none)"
        shown = skipped[:_MAX_SKIPPED_TARGETS]
        summary = ", ".join(shown)
        remaining = len(skipped) - len(shown)
        if remaining > 0:
            summary += f", +{remaining} more"
        return f"Skipped (no commits): {summary}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
