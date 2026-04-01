"""Plan approval modal for the ace TUI."""

import os
from dataclasses import dataclass

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from ..actions.clipboard import copy_to_system_clipboard
from .base import CopyModeForwardingMixin


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", "commit", "epic", or "feedback_requested"
    feedback: str | None = None
    commit_plan: bool = True
    run_coder: bool = True
    coder_prompt_extra: str | None = None


@dataclass
class PlanApprovalOptionsResult:
    """Options returned from the plan approval options modal."""

    commit_plan: bool
    run_coder: bool
    coder_prompt_extra: str | None = None


class PlanApprovalOptionsModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalOptionsResult | None]
):
    """Modal for approve-with-options configuration."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "submit", "Submit"),
        ("tab", "next_field", "Next"),
        ("shift+tab", "prev_field", "Previous"),
        ("space", "toggle_focused", "Toggle"),
    ]

    def __init__(self, plan_file: str) -> None:
        super().__init__()
        self._plan_file = plan_file
        self._commit_plan = True
        self._run_coder = True
        self._focus_index = 0
        self._focusable_ids = [
            "plan-options-commit-toggle",
            "plan-options-run-toggle",
            "plan-options-prompt",
        ]

    def compose(self) -> ComposeResult:
        plan_name = os.path.basename(self._plan_file)
        with Container(id="plan-approval-options-container"):
            yield Static(
                f"[bold cyan]Approve w/ Options[/bold cyan]  [dim]{plan_name}[/dim]",
                id="plan-approval-options-title",
            )
            with Vertical(id="plan-approval-options-form"):
                yield Static(
                    "[bold]Commit plan artifacts[/bold]", classes="plan-options-label"
                )
                yield Button(
                    self._toggle_label("Commit plan artifacts", self._commit_plan),
                    id="plan-options-commit-toggle",
                    variant="primary",
                )

                yield Static(
                    "[bold]Run coder agent[/bold]", classes="plan-options-label"
                )
                yield Button(
                    self._toggle_label("Run coder agent", self._run_coder),
                    id="plan-options-run-toggle",
                    variant="primary",
                )

                yield Static(
                    "[bold]Additional coder prompt[/bold]",
                    classes="plan-options-label",
                )
                yield TextArea(
                    "",
                    id="plan-options-prompt",
                )
            yield Static(
                "[green]Enter[/green]=Submit  [green]Space[/green]=Toggle focused boolean  "
                "[cyan]Tab[/cyan]=Cycle fields  [dim]q[/dim]=Cancel",
                id="plan-approval-options-footer",
            )

    def on_mount(self) -> None:
        self._focus_field(0)

    @staticmethod
    def _toggle_label(name: str, value: bool) -> str:
        return f"{name}: {'ON' if value else 'OFF'}"

    def _focus_field(self, index: int) -> None:
        self._focus_index = index % len(self._focusable_ids)
        widget_id = self._focusable_ids[self._focus_index]
        self.query_one(f"#{widget_id}").focus()

    def _toggle_commit(self) -> None:
        self._commit_plan = not self._commit_plan
        btn = self.query_one("#plan-options-commit-toggle", Button)
        btn.label = self._toggle_label("Commit plan artifacts", self._commit_plan)

    def _toggle_run(self) -> None:
        self._run_coder = not self._run_coder
        btn = self.query_one("#plan-options-run-toggle", Button)
        btn.label = self._toggle_label("Run coder agent", self._run_coder)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_next_field(self) -> None:
        self._focus_field(self._focus_index + 1)

    def action_prev_field(self) -> None:
        self._focus_field(self._focus_index - 1)

    def action_toggle_focused(self) -> None:
        if self._focus_index == 0:
            self._toggle_commit()
        elif self._focus_index == 1:
            self._toggle_run()

    def action_submit(self) -> None:
        text_area = self.query_one("#plan-options-prompt", TextArea)
        extra = text_area.text.strip()
        self.dismiss(
            PlanApprovalOptionsResult(
                commit_plan=self._commit_plan,
                run_coder=self._run_coder,
                coder_prompt_extra=extra or None,
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-options-commit-toggle":
            self._focus_field(0)
            self._toggle_commit()
        elif event.button.id == "plan-options-run-toggle":
            self._focus_field(1)
            self._toggle_run()


class PlanApprovalModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("a", "approve", "Approve"),
        ("A", "approve_with_options", "Approve w/ options"),
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
            "[green]a[/green]=Approve  [green]A[/green]=Approve w/ options  "
            "[red]r[/red]=Reject  [yellow]f[/yellow]=Feedback  "
            "[blue]e[/blue]=Edit  [magenta]E[/magenta]=Epic  "
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

    def action_approve_with_options(self) -> None:
        """Open options modal and return enriched approve response."""

        def _on_options_dismiss(result: PlanApprovalOptionsResult | None) -> None:
            if result is None:
                return
            self.dismiss(
                PlanApprovalResult(
                    action="approve",
                    commit_plan=result.commit_plan,
                    run_coder=result.run_coder,
                    coder_prompt_extra=result.coder_prompt_extra,
                )
            )

        self.app.push_screen(
            PlanApprovalOptionsModal(self._plan_file), _on_options_dismiss
        )

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
