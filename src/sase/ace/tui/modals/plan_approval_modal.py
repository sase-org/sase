"""Plan approval modal for the ace TUI."""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.notification_gates.debug import GateDebugContext
from sase.notification_gates.models import GateExtra
from sase.plan_approval_choices import (
    PlanApprovalModalChoice as PlanApprovalChoice,
    PlanApprovalProtocolFields,
    approval_protocol_for_choice as _approval_protocol_for_choice,
    review_modal_choice_bindings,
)
from sase.plan_gate import (
    PLAN_COMMIT_EXTRA_ID,
    PLAN_RUN_CODER_EXTRA_ID,
    plan_gate_preset_extra_ids,
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
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
) -> "PlanApprovalResult":
    """Build a modal result for a product-level approval choice."""
    protocol = approval_protocol_for_choice(choice)
    return PlanApprovalResult(
        action=protocol.action,
        feedback=feedback,
        commit_plan=(protocol.commit_plan if commit_plan is None else commit_plan),
        run_coder=(protocol.run_coder if run_coder is None else run_coder),
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
        ("d", "debug_view", "Debug"),
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
        allowed_choices: Iterable[PlanApprovalChoice] | None = None,
        approval_extras: Iterable[GateExtra] | None = None,
        debug_context: GateDebugContext | None = None,
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
        self._allowed_choices = frozenset(
            allowed_choices or ("approve", "tale", "epic")
        )
        self._approval_extras = tuple(approval_extras or ())
        self._debug_context = debug_context

    def _build_title_markup(self) -> str:
        """Return the Rich markup string used for the modal title."""
        plan_name = os.path.basename(self._plan_file)
        badge = _provider_badge_markup(self._llm_provider, self._model)
        badge_segment = f"  {badge}" if badge else ""
        title = (
            "Epic Review"
            if getattr(self, "_default_choice", "approve") == "epic"
            else "Plan Review"
        )
        return f"[bold cyan]{title}[/bold cyan]{badge_segment}  [dim]{plan_name}[/dim]"

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        default_choice = cast(
            PlanApprovalChoice, getattr(self, "_default_choice", "approve")
        )
        allowed_choices = getattr(
            self, "_allowed_choices", frozenset(("approve", "tale", "epic"))
        )
        remodeled = bool(getattr(self, "_approval_extras", ()))
        default_label = "Approve" if remodeled else default_choice.title()
        choice_hints = "  ".join(
            hint
            for choice, hint in (
                ("approve", "[green]a[/green]=Approve"),
                ("tale", "[green]t[/green]=Tale"),
                ("epic", "[magenta]E[/magenta]=Epic"),
            )
            if choice in allowed_choices
        )
        custom_hint = (
            "  [green]c[/green]=Custom" if {"approve", "tale"} & allowed_choices else ""
        )
        hints = (
            f"[green]enter[/green]={default_label}  "
            f"{choice_hints}{custom_hint}  [red]r[/red]=Reject  "
            "[yellow]f[/yellow]=Feedback  "
            "[blue]e[/blue]=Edit  "
            "[cyan]y[/cyan]=Copy  [cyan]Y[/cyan]=Copy path  "
            "[cyan]d[/cyan]=Debug  [dim]q[/dim]=Cancel  |  Ctrl+D/U / g / G to scroll"
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

            if remodeled:
                from .custom_gate_modal import GateExtrasSelectionList

                yield Static(
                    "[bold]Approve with optional add-on commands[/bold]",
                    id="plan-approval-extras-label",
                )
                yield GateExtrasSelectionList(
                    self._approval_extras,
                    id="plan-approval-extras",
                )

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

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_approve(self) -> None:
        """Apply the legacy plain-approval preset."""
        if not self._choice_allowed("approve"):
            return
        if self._has_approval_extras():
            self.dismiss(
                self._result_for_extra_ids(plan_gate_preset_extra_ids("approve"))
            )
            return
        self.dismiss(_plan_approval_result_for_choice("approve"))

    def action_approve_default(self) -> None:
        """Approve using the current extras, or the authored legacy tier."""
        if self._has_approval_extras():
            from .custom_gate_modal import GateExtrasSelectionList

            selected = self.query_one(
                "#plan-approval-extras", GateExtrasSelectionList
            ).selected_extra_ids
            self.dismiss(self._result_for_extra_ids(selected))
            return
        default_choice = cast(
            PlanApprovalChoice, getattr(self, "_default_choice", "approve")
        )
        if not self._choice_allowed(default_choice):
            return
        self.dismiss(_plan_approval_result_for_choice(default_choice))

    def action_tale(self) -> None:
        """Apply the legacy tale preset."""
        if not self._choice_allowed("tale"):
            return
        if self._has_approval_extras():
            self.dismiss(self._result_for_extra_ids(plan_gate_preset_extra_ids("tale")))
            return
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
                (
                    "approve"
                    if self._has_approval_extras() and result.choice != "epic"
                    else result.choice
                ),
                coder_prompt=result.coder_prompt,
                coder_model=result.coder_model,
                commit_plan=result.commit_plan,
                run_coder=result.run_coder,
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
        allowed_choices = getattr(
            self, "_allowed_choices", frozenset(("approve", "tale", "epic"))
        )
        if not {"approve", "tale"} & allowed_choices:
            self.notify(
                "Custom approval is not available for this gate",
                severity="warning",
            )
            return
        if self._has_approval_extras():
            commit_plan, run_coder = self._selected_approval_flags()
            choice: PlanApprovalChoice = "tale" if commit_plan else "approve"
            self._push_approve_options(
                commit_plan=commit_plan,
                run_coder=run_coder,
                choice=choice,
            )
            return
        self._push_approve_options(choice=getattr(self, "_default_choice", "approve"))

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
        if not self._choice_allowed("epic"):
            return
        self.dismiss(_plan_approval_result_for_choice("epic"))

    def _choice_allowed(self, choice: PlanApprovalChoice) -> bool:
        allowed_choices = getattr(
            self, "_allowed_choices", frozenset(("approve", "tale", "epic"))
        )
        if choice in allowed_choices:
            return True
        self.notify(
            "Choice is not present in this approval request",
            severity="warning",
        )
        return False

    def _has_approval_extras(self) -> bool:
        return bool(getattr(self, "_approval_extras", ()))

    def _selected_approval_flags(self) -> tuple[bool, bool]:
        from .custom_gate_modal import GateExtrasSelectionList

        selected = set(
            self.query_one(
                "#plan-approval-extras", GateExtrasSelectionList
            ).selected_extra_ids
        )
        return (
            PLAN_COMMIT_EXTRA_ID in selected,
            PLAN_RUN_CODER_EXTRA_ID in selected,
        )

    def _result_for_extra_ids(
        self, selected_extra_ids: Iterable[str] | None
    ) -> PlanApprovalResult:
        selected = set(selected_extra_ids or ())
        return _plan_approval_result_for_choice(
            "approve",
            commit_plan=PLAN_COMMIT_EXTRA_ID in selected,
            run_coder=PLAN_RUN_CODER_EXTRA_ID in selected,
        )

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
