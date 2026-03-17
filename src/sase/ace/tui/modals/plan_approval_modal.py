"""Plan approval modal for the ace TUI."""

import os
from dataclasses import dataclass

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .base import CopyModeForwardingMixin


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", or "epic"
    feedback: str | None = None


class PlanApprovalModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("a", "approve", "Approve"),
        ("r", "reject", "Reject"),
        ("f", "feedback", "Reject w/ feedback"),
        ("e", "edit", "Edit"),
        ("E", "epic", "Epic"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, plan_file: str, *, beads_supported: bool = False) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
            beads_supported: Whether beads-based epic creation is available.
        """
        super().__init__()
        self._plan_file = plan_file
        self._feedback_mode = False
        self._beads_supported = beads_supported

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        plan_name = os.path.basename(self._plan_file)
        epic_hint = "[magenta]E[/magenta]=Epic  " if self._beads_supported else ""
        hints = (
            "[green]a[/green]=Approve  [red]r[/red]=Reject  "
            "[yellow]f[/yellow]=Reject w/ feedback  "
            "[blue]e[/blue]=Edit  "
            f"{epic_hint}"
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
            yield Input(
                placeholder="Enter feedback and press Enter...",
                id="plan-approval-feedback",
            )

    def on_mount(self) -> None:
        """Hide the feedback input initially."""
        feedback_input = self.query_one("#plan-approval-feedback", Input)
        feedback_input.add_class("hidden")

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
        if self._feedback_mode:
            return
        self.dismiss(PlanApprovalResult(action="approve"))

    def action_reject(self) -> None:
        """Reject the plan without feedback."""
        if self._feedback_mode:
            return
        self.dismiss(PlanApprovalResult(action="reject"))

    def action_edit(self) -> None:
        """Edit the plan file in an external editor."""
        if self._feedback_mode:
            return
        self.dismiss(PlanApprovalResult(action="edit"))

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        if self._feedback_mode or not self._beads_supported:
            return
        self.dismiss(PlanApprovalResult(action="epic"))

    def action_feedback(self) -> None:
        """Enter feedback mode to reject with feedback."""
        if self._feedback_mode:
            return
        self._feedback_mode = True
        feedback_input = self.query_one("#plan-approval-feedback", Input)
        feedback_input.remove_class("hidden")
        feedback_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle feedback submission."""
        if event.input.id == "plan-approval-feedback":
            feedback = event.value.strip()
            if feedback:
                self.dismiss(PlanApprovalResult(action="reject", feedback=feedback))
            else:
                # Empty feedback - exit feedback mode
                self._feedback_mode = False
                event.input.add_class("hidden")

    def on_key(self, event: object) -> None:
        """Handle escape in feedback mode."""
        from textual import events

        if not isinstance(event, events.Key):
            super().on_key(event)  # type: ignore[arg-type]
            return

        if self._feedback_mode and event.key == "escape":
            self._feedback_mode = False
            feedback_input = self.query_one("#plan-approval-feedback", Input)
            feedback_input.add_class("hidden")
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)  # type: ignore[arg-type]
