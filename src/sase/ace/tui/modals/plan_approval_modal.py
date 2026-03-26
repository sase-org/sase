"""Plan approval modal for the ace TUI."""

import os
from dataclasses import dataclass

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..actions.clipboard import copy_to_system_clipboard
from .base import CopyModeForwardingMixin


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", "commit", "epic", or "feedback_requested"
    feedback: str | None = None


class PlanApprovalModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("a", "approve", "Approve"),
        ("c", "commit", "Commit"),
        ("r", "reject", "Reject"),
        ("f", "feedback", "Feedback"),
        ("e", "edit", "Edit"),
        ("E", "epic", "Epic"),
        ("y", "copy_plan", "Copy"),
        ("Y", "copy_plan_path", "Copy path"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, plan_file: str) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
        """
        super().__init__()
        self._plan_file = plan_file

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        plan_name = os.path.basename(self._plan_file)
        hints = (
            "[green]a[/green]=Approve  [green]c[/green]=Commit  [red]r[/red]=Reject  "
            "[yellow]f[/yellow]=Feedback  "
            "[blue]e[/blue]=Edit  "
            "[magenta]E[/magenta]=Epic  "
            "[cyan]y[/cyan]=Copy  [cyan]Y[/cyan]=Copy path  "
            "[dim]q[/dim]=Cancel  |  Ctrl+D/U to scroll"
        )

        with Container(id="plan-approval-container"):
            yield Static(
                f"[bold cyan]Plan Review[/bold cyan]  [dim]{plan_name}[/dim]",
                id="plan-approval-title",
            )

            with VerticalScroll(id="plan-approval-scroll"):
                # Read and display plan file content
                content = self._read_plan_file()
                syntax = Syntax(
                    content,
                    "markdown",
                    theme="monokai",
                    word_wrap=True,
                )
                yield Static(syntax, id="plan-approval-content")

            yield Static(hints, id="plan-approval-footer")

    def _read_plan_file(self) -> str:
        """Read the plan file content."""
        expanded = os.path.expanduser(self._plan_file)
        try:
            with open(expanded, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"[Error reading plan file: {e}]"

    def action_scroll_down(self) -> None:
        """Scroll the content down by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the content up by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_cancel(self) -> None:
        """Cancel the modal (no response written)."""
        self.dismiss(None)

    def action_approve(self) -> None:
        """Approve the plan."""
        self.dismiss(PlanApprovalResult(action="approve"))

    def action_commit(self) -> None:
        """Commit the plan without running a coder agent."""
        self._copy_plan_path_to_clipboard()
        self.dismiss(PlanApprovalResult(action="commit"))

    def action_reject(self) -> None:
        """Reject the plan without feedback."""
        self.dismiss(PlanApprovalResult(action="reject"))

    def action_edit(self) -> None:
        """Edit the plan file in an external editor."""
        self.dismiss(PlanApprovalResult(action="edit"))

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        self.dismiss(PlanApprovalResult(action="epic"))

    def action_copy_plan(self) -> None:
        """Copy the plan file contents to clipboard."""
        content = self._read_plan_file()
        if content.startswith("[Error"):
            self.notify("Failed to read plan file", severity="error")
            return
        if copy_to_system_clipboard(content):
            self.notify("Copied: Plan")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def _copy_plan_path_to_clipboard(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        home = os.path.expanduser("~")
        path = os.path.expanduser(self._plan_file)
        if path.startswith(home):
            path = "~" + path[len(home) :]
        if copy_to_system_clipboard(path):
            self.notify(f"Copied: {path}")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_copy_plan_path(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        self._copy_plan_path_to_clipboard()

    def action_feedback(self) -> None:
        """Dismiss modal and request feedback via PromptInputBar."""
        self.dismiss(PlanApprovalResult(action="feedback_requested"))
