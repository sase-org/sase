"""Plan approval modal for the ace TUI."""

import os
from dataclasses import dataclass

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.plan_approval_choices import (
    PlanApprovalModalChoice as PlanApprovalChoice,
    PlanApprovalProtocolFields,
    approval_protocol_for_choice as _approval_protocol_for_choice,
    review_modal_choice_bindings,
    review_modal_choice_hints_markup,
)

from ..actions.clipboard import copy_to_system_clipboard
from .base import CopyModeForwardingMixin


def approval_protocol_for_choice(
    choice: PlanApprovalChoice,
) -> PlanApprovalProtocolFields:
    """Map a product-level approval choice to the existing response protocol."""
    return _approval_protocol_for_choice(choice)


def _plan_approval_result_for_choice(
    choice: PlanApprovalChoice,
    *,
    feedback: str | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
) -> "PlanApprovalResult":
    """Build a modal result for a product-level approval choice."""
    protocol = approval_protocol_for_choice(choice)
    return PlanApprovalResult(
        action=protocol.action,
        feedback=feedback,
        commit_plan=protocol.commit_plan,
        run_coder=protocol.run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        choice=choice,
    )


def _provider_badge_markup(llm_provider: str | None, model: str | None) -> str:
    """Render a Rich-markup badge like ``CLAUDE(opus)`` with provider theming.

    Returns an empty string when neither field is set, so callers can collapse
    the title to its unbadged form.
    """
    from sase.ace.tui.provider_styles import provider_model_badge_markup

    return provider_model_badge_markup(llm_provider, model)


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", "epic", "feedback_requested", or "approve_prompt_edit"
    feedback: str | None = None
    commit_plan: bool = True
    run_coder: bool = True
    coder_prompt: str | None = None
    coder_model: str | None = None
    choice: PlanApprovalChoice | None = None


@dataclass
class PendingApproveState:
    """State to restore when re-opening PlanApprovalModal after prompt editing."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None = None
    choice: PlanApprovalChoice | None = None


class PlanApprovalModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "approve_default", "Default"),
        *review_modal_choice_bindings(),
        ("c", "custom", "Custom"),
        ("r", "reject", "Reject"),
        ("f", "feedback", "Feedback"),
        ("e", "edit", "Edit"),
        ("y", "copy_plan", "Copy"),
        ("Y", "copy_plan_path", "Copy path"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(
        self,
        plan_file: str,
        pending_approve_state: PendingApproveState | None = None,
        *,
        llm_provider: str | None = None,
        model: str | None = None,
        default_choice: PlanApprovalChoice | None = None,
    ) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
            pending_approve_state: If set, auto-push the custom approval modal on mount
                with the given state (used after prompt editing round-trip).
            llm_provider: Provider that produced the plan (e.g. "claude"), for
                display in the modal title. Optional — when absent the title
                omits the provider badge.
            model: Model that produced the plan (e.g. "opus"), for display in
                the modal title alongside the provider.
        """
        super().__init__()
        self._plan_file = plan_file
        self._pending_approve_state = pending_approve_state
        self._llm_provider = llm_provider
        self._model = model
        self._default_choice: PlanApprovalChoice = default_choice or "approve"

    def _build_title_markup(self) -> str:
        """Return the Rich markup string used for the modal title."""
        plan_name = os.path.basename(self._plan_file)
        badge = _provider_badge_markup(self._llm_provider, self._model)
        badge_segment = f"  {badge}" if badge else ""
        return (
            f"[bold cyan]Plan Review[/bold cyan]{badge_segment}  [dim]{plan_name}[/dim]"
        )

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        default_label = self._default_choice.title()
        hints = (
            f"[green]enter[/green]={default_label}  "
            f"{review_modal_choice_hints_markup()}  [green]c[/green]=Custom  [red]r[/red]=Reject  "
            "[yellow]f[/yellow]=Feedback  "
            "[blue]e[/blue]=Edit  "
            "[cyan]y[/cyan]=Copy  [cyan]Y[/cyan]=Copy path  "
            "[dim]q[/dim]=Cancel  |  Ctrl+D/U / g / G to scroll"
        )

        with Container(id="plan-approval-container"):
            yield Static(
                self._build_title_markup(),
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

    def on_mount(self) -> None:
        if self._pending_approve_state is not None:
            state = self._pending_approve_state
            self._pending_approve_state = None
            self._push_approve_options(
                commit_plan=state.commit_plan,
                run_coder=state.run_coder,
                coder_prompt=state.coder_prompt,
                coder_model=state.coder_model,
                choice=state.choice,
            )

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

    def action_scroll_to_top(self) -> None:
        """Scroll the content to the very top."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll the content to the very bottom."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def action_cancel(self) -> None:
        """Cancel the modal (no response written)."""
        self.dismiss(None)

    def action_approve(self) -> None:
        """Approve the plan without an SDD commit."""
        self.dismiss(_plan_approval_result_for_choice("approve"))

    def action_approve_default(self) -> None:
        """Approve using the tier authored in the pending plan."""
        self.dismiss(_plan_approval_result_for_choice(self._default_choice))

    def action_tale(self) -> None:
        """Approve the plan as an SDD tale."""
        self.dismiss(_plan_approval_result_for_choice("tale"))

    def _push_approve_options(
        self,
        commit_plan: bool = True,
        run_coder: bool = True,
        coder_prompt: str = "",
        coder_model: str | None = None,
        choice: PlanApprovalChoice | None = None,
    ) -> None:
        """Push the custom approval modal with the given initial state."""
        from .approve_options_modal import (
            ApproveOptionsEditPrompt,
            ApproveOptionsModal,
            ApproveOptionsResult,
        )

        def on_options_dismiss(
            result: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            if result is None:
                return
            if isinstance(result, ApproveOptionsEditPrompt):
                self.dismiss(
                    PlanApprovalResult(
                        action="approve_prompt_edit",
                        commit_plan=result.commit_plan,
                        run_coder=result.run_coder,
                        coder_prompt=result.coder_prompt,
                        coder_model=result.coder_model,
                        choice=result.choice,
                    )
                )
                return
            approval_result = _plan_approval_result_for_choice(
                result.choice,
                coder_prompt=result.coder_prompt,
                coder_model=result.coder_model,
            )
            self.dismiss(approval_result)

        self.app.push_screen(
            ApproveOptionsModal(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
                coder_model=coder_model,
                choice=choice,
                planner_llm_provider=self._llm_provider,
            ),
            on_options_dismiss,
        )

    def action_custom(self) -> None:
        """Open the custom approval modal."""
        self._push_approve_options(choice=self._default_choice)

    def action_approve_options(self) -> None:
        """Backward-compatible alias for the old action name."""
        self.action_custom()

    def action_reject(self) -> None:
        """Reject the plan without feedback."""
        self.dismiss(PlanApprovalResult(action="reject"))

    def action_edit(self) -> None:
        """Edit the plan file in an external editor."""
        self.dismiss(PlanApprovalResult(action="edit"))

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        self.dismiss(_plan_approval_result_for_choice("epic"))

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
