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


def _provider_badge_markup(llm_provider: str | None, model: str | None) -> str:
    """Render a Rich-markup badge like ``CLAUDE(opus)`` with provider theming.

    Returns an empty string when neither field is set, so callers can collapse
    the title to its unbadged form.
    """
    if not llm_provider and not model:
        return ""

    provider = (llm_provider or "").lower()
    if not provider and model:
        if model in ("opus", "sonnet", "haiku"):
            provider = "claude"
        elif "gemini" in model.lower():
            provider = "gemini"
        elif model.startswith(("gpt-", "o3", "o4")):
            provider = "codex"

    if provider == "claude":
        name_style, paren_style, model_style = "bold #FF5F00", "#D75F00", "#FFAF00"
    elif provider == "codex":
        name_style, paren_style, model_style = "bold #87FF00", "#5FAF00", "#AFFF5F"
    elif provider == "gemini":
        name_style, paren_style, model_style = "bold #4285F4", "#5F87D7", "#87AFFF"
    else:
        # Unknown/other provider: fall back to the plain-text label with a
        # neutral muted color, matching the fallback in append_model_field.
        from sase.llm_provider.registry import format_provider_model_label

        label = format_provider_model_label(llm_provider, model)
        return f"[#AF87D7]{label}[/]"

    provider_name = provider.upper()
    if model:
        return (
            f"[{name_style}]{provider_name}[/]"
            f"[{paren_style}]([/]"
            f"[{model_style}]{model}[/]"
            f"[{paren_style}])[/]"
        )
    return f"[{name_style}]{provider_name}[/]"


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", "epic", "legend", "feedback_requested", or "approve_prompt_edit"
    feedback: str | None = None
    commit_plan: bool = True
    run_coder: bool = True
    coder_prompt: str | None = None
    coder_model: str | None = None


@dataclass
class PendingApproveState:
    """State to restore when re-opening PlanApprovalModal after prompt editing."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None = None


class PlanApprovalModal(
    CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("a", "approve", "Approve"),
        ("A", "approve_options", "Options"),
        ("r", "reject", "Reject"),
        ("f", "feedback", "Feedback"),
        ("e", "edit", "Edit"),
        ("E", "epic", "Epic"),
        ("L", "legend", "Legend"),
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
    ) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
            pending_approve_state: If set, auto-push ApproveOptionsModal on mount
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
        hints = (
            "[green]a[/green]=Approve  [green]A[/green]=Options  [red]r[/red]=Reject  "
            "[yellow]f[/yellow]=Feedback  "
            "[blue]e[/blue]=Edit  "
            "[magenta]E[/magenta]=Epic  "
            "[magenta]L[/magenta]=Legend  "
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
        """Approve the plan."""
        self.dismiss(PlanApprovalResult(action="approve"))

    def _push_approve_options(
        self,
        commit_plan: bool = True,
        run_coder: bool = True,
        coder_prompt: str = "",
        coder_model: str | None = None,
    ) -> None:
        """Push the approve-with-options modal with the given initial state."""
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
                    )
                )
                return
            self.dismiss(
                PlanApprovalResult(
                    action="approve",
                    commit_plan=result.commit_plan,
                    run_coder=result.run_coder,
                    coder_prompt=result.coder_prompt,
                    coder_model=result.coder_model,
                )
            )

        self.app.push_screen(
            ApproveOptionsModal(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
                coder_model=coder_model,
            ),
            on_options_dismiss,
        )

    def action_approve_options(self) -> None:
        """Open the approve-with-options modal."""
        self._push_approve_options()

    def action_reject(self) -> None:
        """Reject the plan without feedback."""
        self.dismiss(PlanApprovalResult(action="reject"))

    def action_edit(self) -> None:
        """Edit the plan file in an external editor."""
        self.dismiss(PlanApprovalResult(action="edit"))

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        self.dismiss(PlanApprovalResult(action="epic"))

    def action_legend(self) -> None:
        """Create a legend from the plan."""
        self.dismiss(PlanApprovalResult(action="legend"))

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
