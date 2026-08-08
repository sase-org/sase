"""Plan approval modal for the ace TUI.

This module owns the modal itself: its layout, its scrolling and copy
shortcuts, and how it is wired to the shared gate machinery. The pieces that
are not about the screen live beside it — the branch model defaults in
:mod:`~sase.ace.tui.modals.plan_approval_gate_data`, the result protocol in
:mod:`~sase.ace.tui.modals.plan_approval_results`, the decision handling in
:mod:`~sase.ace.tui.modals.plan_approval_decisions`, and the hint line in
:mod:`~sase.ace.tui.modals.plan_approval_footer`.
"""

import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.notification_gates.debug import GateDebugContext

from ..actions.clipboard import schedule_copy_delivery
from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
)
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin
from .gate_action_controls import GateActionsData
from .gate_action_runner import (
    GateActionRunner,
    GateActionsMixin,
    gate_modal_taken_keys,
)
from .gate_branch_controls import GateBranchControls, GateBranchData
from .plan_approval_decisions import PlanApprovalDecisionsMixin
from .plan_approval_footer import plan_approval_footer_text
from .plan_approval_gate_data import (
    DEFAULT_GATE_KEYMAPS,
    HOST_COLLECTED_PROPERTIES,
    PLAN_GATE_STATIC_BINDINGS,
    default_plan_gate_data,
)
from .plan_approval_results import (
    PendingApproveState,
    PlanApprovalChoice,
    PlanApprovalResult,
)


def _provider_badge_markup(llm_provider: str | None, model: str | None) -> str:
    """Render a Rich-markup badge like ``CLAUDE(opus)`` with provider theming.

    Returns an empty string when neither field is set, so callers can collapse
    the title to its unbadged form.
    """
    from sase.ace.tui.provider_styles import provider_model_badge_markup

    return provider_model_badge_markup(llm_provider, model)


class PlanApprovalModal(
    PlanApprovalDecisionsMixin,
    GateActionsMixin,
    CopyModeForwardingMixin,
    ModalScreen[PlanApprovalResult | None],
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

    BINDINGS = [
        *PLAN_GATE_STATIC_BINDINGS,
        *build_gate_modal_bindings(DEFAULT_GATE_KEYMAPS),
        *build_gate_numbered_branch_bindings(),
    ]

    def __init__(
        self,
        plan_file: str,
        pending_approve_state: PendingApproveState | None = None,
        *,
        copy_plan_path: str | None = None,
        llm_provider: str | None = None,
        model: str | None = None,
        default_choice: PlanApprovalChoice | None = None,
        gate: GateBranchData | None = None,
        plan_content: str | None = None,
        debug_context: GateDebugContext | None = None,
        gate_keymaps: GateModalKeymaps | None = None,
        actions: GateActionsData | None = None,
        action_runner: GateActionRunner | None = None,
    ) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
            pending_approve_state: If set, auto-push the custom approval modal on mount
                with the given state (used after prompt editing round-trip).
            copy_plan_path: Durable plan path copied by the path shortcut. Falls back
                to ``plan_file`` for direct and legacy callers.
            llm_provider: Provider that produced the plan (e.g. "claude"), for
                display in the modal title. Optional — when absent the title
                omits the provider badge.
            model: Model that produced the plan (e.g. "opus"), for display in
                the modal title alongside the provider.
        """
        super().__init__()
        self._plan_file = plan_file
        self._copy_plan_path = copy_plan_path or plan_file
        self._pending_approve_state = pending_approve_state
        self._llm_provider = llm_provider
        self._model = model
        self._default_choice: PlanApprovalChoice = default_choice or "approve"
        self._gate = gate or default_plan_gate_data(self._default_choice)
        self._plan_content = plan_content
        self._debug_context = debug_context
        self._gate_keymaps = gate_keymaps or DEFAULT_GATE_KEYMAPS
        self._init_gate_actions(
            actions,
            action_runner,
            taken_keys=gate_modal_taken_keys(
                PLAN_GATE_STATIC_BINDINGS, self._gate_keymaps
            ),
        )
        self._bindings = BindingsMap(
            [
                *PLAN_GATE_STATIC_BINDINGS,
                *build_gate_modal_bindings(self._gate_keymaps),
                *build_gate_numbered_branch_bindings(),
                *self._gate_action_bindings(),
            ]
        )

    def _build_title_markup(self) -> str:
        """Return the Rich markup string used for the modal title."""
        badge = _provider_badge_markup(self._llm_provider, self._model)
        badge_segment = f"  {badge}" if badge else ""
        title = (
            "Epic Review"
            if getattr(self, "_default_choice", "approve") == "epic"
            else "Plan Review"
        )
        return f"[bold cyan]{title}[/bold cyan]{badge_segment}"

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(
            id="plan-approval-container",
            classes="gate-review-shell",
        ):
            yield Static(
                self._build_title_markup(),
                id="plan-approval-title",
                classes="gate-review-header",
            )

            with Container(classes="gate-review-body"):
                with VerticalScroll(classes="gate-review-actions"):
                    yield from self._compose_gate_actions()
                    yield Static("Decision", classes="gate-review-section-title")
                    yield GateBranchControls(
                        self._gate,
                        host_collected_properties=HOST_COLLECTED_PROPERTIES,
                        id="plan-approval-branches",
                        classes="gate-branch-controls--stacked",
                    )
                    yield Button(
                        "Cancel",
                        id="plan-approval-cancel",
                        classes="gate-review-cancel",
                    )

                review_scroll = VerticalScroll(
                    id="plan-approval-scroll",
                    classes="gate-review-document",
                )
                review_scroll.border_title = Text(os.path.basename(self._plan_file))
                with review_scroll:
                    # Read and display plan file content
                    content = (
                        self._plan_content
                        if self._plan_content is not None
                        else self._read_plan_file()
                    )
                    syntax = markdown_document_syntax(content)
                    yield Static(syntax, id="plan-approval-content")

            yield Static(
                self._footer_text(),
                id="plan-approval-footer",
                classes="gate-review-footer",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-approval-cancel":
            self.action_cancel()

    def _footer_text(self) -> Text:
        """Return footer hints with the declared primary action emphasized."""
        return plan_approval_footer_text(
            self._gate,
            self._gate_keymaps,
            self.gate_action_hints(separator="="),
        )

    def on_mount(self) -> None:
        self._sync_submission_block()
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
            return
        self.focus_gate_control(1)

    def render_reviewed_content(self, content: str) -> None:
        """Re-render the plan pane in place after an accepted edit action."""
        self._plan_content = content
        self.query_one("#plan-approval-content", Static).update(
            markdown_document_syntax(content)
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

    def action_next_control(self) -> None:
        self.focus_gate_control(1)

    def action_previous_control(self) -> None:
        self.focus_gate_control(-1)

    def action_toggle_option(self) -> None:
        self.query_one(GateBranchControls).toggle_focused_option()

    def action_submit_primary(self) -> None:
        self.query_one(GateBranchControls).submit_primary_branch()

    def action_submit_branch(self) -> None:
        self.query_one(GateBranchControls).submit_active_branch()

    def action_submit_numbered_branch(self, branch_index: int) -> None:
        self.query_one(GateBranchControls).submit_numbered_branch(branch_index)

    def action_copy_plan(self) -> None:
        """Copy the plan file contents to clipboard."""

        def content() -> str:
            value = (
                self._plan_content
                if self._plan_content is not None
                else self._read_plan_file()
            )
            if value.startswith("[Error"):
                raise RuntimeError("failed to read plan file")
            return value

        schedule_copy_delivery(
            self,
            content,
            copied_label="all plan contents",
            task_name="sase-copy-plan-contents",
        )

    def _copy_plan_path_to_clipboard(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        home = os.path.expanduser("~")
        path = os.path.expanduser(self._copy_plan_path)
        if path.startswith(home):
            path = "~" + path[len(home) :]
        schedule_copy_delivery(
            self,
            path,
            copied_label=f"plan path ({path})",
            task_name="sase-copy-plan-path",
        )

    def action_copy_plan_path(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        self._copy_plan_path_to_clipboard()
