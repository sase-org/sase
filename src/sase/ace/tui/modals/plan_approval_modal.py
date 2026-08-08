"""Plan approval modal for the ace TUI."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.notification_gates.debug import GateDebugContext
from sase.notification_gates.models import GateGroup, GateOption
from sase.plan_approval_choices import (
    PlanApprovalModalChoice as PlanApprovalChoice,
    PlanApprovalProtocolFields,
    approval_protocol_for_choice as _approval_protocol_for_choice,
)
from sase.plan_gate import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_COMMIT_OPTION_ID,
    TALE_PLAN_SUBMIT_GROUP,
    PlanGateTier,
    plan_gate_option_icon,
    plan_gate_option_label,
)
from ..actions.clipboard import schedule_copy_delivery
from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
    key_display_name,
    load_builtin_gate_defaults,
)
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin
from .gate_action_controls import GateActionsData
from .gate_action_runner import (
    GateActionRunner,
    GateActionsMixin,
    gate_modal_taken_keys,
)
from .gate_branch_controls import (
    GateBranchControls,
    GateBranchData,
    gate_declares_inputs,
)
from .gate_primary_footer import primary_action_badge


_PLAN_GATE_STATIC_BINDINGS = [
    ("escape", "cancel", "Cancel"),
    ("q", "cancel", "Cancel"),
    ("d", "debug_view", "Debug"),
    ("c", "custom", "Custom"),
    ("y", "copy_plan_path", "Copy path"),
    ("Y", "copy_plan", "Copy all contents"),
    ("ctrl+d", "scroll_down", "Scroll down"),
    ("ctrl+u", "scroll_up", "Scroll up"),
    ("g", "scroll_to_top", "Top"),
    ("G", "scroll_to_bottom", "Bottom"),
]
_DEFAULT_GATE_KEYMAPS = GateModalKeymaps(**load_builtin_gate_defaults())
#: Coder-option fields are already collected by the "c" ApproveOptionsModal
#: (`coder_prompt`/`coder_model`) and by the host's own epic launch choice
#: (`epic_launch_mode`), so the raw-schema escape hatch must not duplicate
#: them with a YAML box on every plan and epic gate.
_HOST_COLLECTED_PROPERTIES = frozenset(
    {"feedback", "coder_prompt", "coder_model", "epic_launch_mode"}
)


def _default_plan_gate_data(default_choice: PlanApprovalChoice) -> GateBranchData:
    """Build a display-only branch model for direct/legacy modal callers."""
    tier: PlanGateTier = "epic" if default_choice == "epic" else "tale"
    definitions: tuple[tuple[str, str, str, str], ...] = (
        (
            "approve",
            plan_gate_option_label("approve", tier=tier),
            plan_gate_option_icon("approve", tier=tier),
            "disabled",
        ),
        (
            "commit",
            plan_gate_option_label("commit", tier=tier),
            plan_gate_option_icon("commit", tier=tier),
            "disabled",
        ),
        (
            "reject",
            plan_gate_option_label("reject", tier=tier),
            plan_gate_option_icon("reject", tier=tier),
            "disabled",
        ),
        (
            "feedback",
            plan_gate_option_label("feedback", tier=tier),
            plan_gate_option_icon("feedback", tier=tier),
            "required",
        ),
    )
    if default_choice == "epic":
        definitions = tuple(item for item in definitions if item[0] != "commit")
        query = "approve OR reject OR feedback"
        branches: tuple[tuple[str, ...], ...] = (
            ("approve",),
            ("reject",),
            ("feedback",),
        )
        groups: tuple[GateGroup, ...] = ()
    else:
        query = "(approve AND commit) OR reject OR feedback"
        branches = (("approve", "commit"), ("reject",), ("feedback",))
        groups = (TALE_PLAN_SUBMIT_GROUP,)
    options = tuple(
        GateOption.from_mapping(
            {
                "id": option_id,
                "label": label,
                "icon": icon,
                "command": {"argv": [f"commands/{option_id}"]},
                "feedback": feedback,
            },
            index,
        )
        for index, (option_id, label, icon, feedback) in enumerate(definitions)
    )
    return GateBranchData(
        query=query,
        options=options,
        groups=groups,
        branches=branches,
        primary_branch=branches[0],
    )


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
    effective_commit = protocol.commit_plan if commit_plan is None else commit_plan
    effective_run = protocol.run_coder if run_coder is None else run_coder
    selected_option_ids = (
        (PLAN_APPROVE_OPTION_ID,)
        if choice == "epic"
        else tuple(
            option_id
            for option_id, selected in (
                (PLAN_APPROVE_OPTION_ID, effective_run),
                (PLAN_COMMIT_OPTION_ID, effective_commit),
            )
            if selected
        )
    )
    return PlanApprovalResult(
        action=protocol.action,
        feedback=feedback,
        commit_plan=effective_commit,
        run_coder=effective_run,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        choice=choice,
        selected_option_ids=selected_option_ids,
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
    selected_option_ids: tuple[str, ...] = ()
    option_inputs: Mapping[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PendingApproveState:
    """State to restore when re-opening PlanApprovalModal after prompt editing."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None = None
    choice: PlanApprovalChoice | None = None


class PlanApprovalModal(
    GateActionsMixin, CopyModeForwardingMixin, ModalScreen[PlanApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

    BINDINGS = [
        *_PLAN_GATE_STATIC_BINDINGS,
        *build_gate_modal_bindings(_DEFAULT_GATE_KEYMAPS),
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
        self._gate = gate or _default_plan_gate_data(self._default_choice)
        self._plan_content = plan_content
        self._debug_context = debug_context
        self._gate_keymaps = gate_keymaps or _DEFAULT_GATE_KEYMAPS
        self._init_gate_actions(
            actions,
            action_runner,
            taken_keys=gate_modal_taken_keys(
                _PLAN_GATE_STATIC_BINDINGS, self._gate_keymaps
            ),
        )
        self._bindings = BindingsMap(
            [
                *_PLAN_GATE_STATIC_BINDINGS,
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
                        host_collected_properties=_HOST_COLLECTED_PROPERTIES,
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
        keys = self._gate_keymaps
        hints = Text()
        hints.append(
            f"{key_display_name(keys.next_control)}/"
            f"{key_display_name(keys.previous_control)}",
            style="green",
        )
        hints.append("=Navigate  ")
        hints.append(key_display_name(keys.toggle_option), style="green")
        hints.append("=Toggle  ")
        hints.append_text(primary_action_badge(self._gate, keys.submit_primary))
        hints.append("  ")
        hints.append(key_display_name(keys.submit_branch), style="green")
        hints.append("=Submit  ")
        _has_inputs, has_path = gate_declares_inputs(
            self._gate.options, _HOST_COLLECTED_PROPERTIES
        )
        if has_path:
            hints.append("^t", style="green")
            hints.append("=Complete path  ")
        hints.append("c", style="green")
        hints.append("=Coder options  ")
        hints.append_text(self.gate_action_hints(separator="="))
        hints.append("y", style="cyan")
        hints.append("=Copy path  ")
        hints.append("Y", style="cyan")
        hints.append("=Copy all contents  ")
        hints.append("d", style="cyan")
        hints.append("=Debug  ")
        hints.append("q", style="dim")
        hints.append("=Cancel  |  Ctrl+D/U / g / G to scroll")
        return hints

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

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        event.stop()
        self.dismiss(
            self._result_for_selection(
                event.selected_option_ids,
                feedback=event.feedback,
                option_inputs=event.option_inputs,
            )
        )

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

    def action_approve(self) -> None:
        """Backward-compatible programmatic plain-approval action."""
        if not self._choice_allowed("approve"):
            return
        self.dismiss(_plan_approval_result_for_choice("approve"))

    def action_approve_default(self) -> None:
        """Backward-compatible alias for submitting the active branch."""
        self.action_submit_branch()

    def action_tale(self) -> None:
        """Backward-compatible programmatic tale selection."""
        if not self._choice_allowed("tale"):
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
                        selected_option_ids=self._approval_selection(
                            result.commit_plan,
                            result.run_coder,
                        ),
                    )
                )
                return
            approval_result = self._result_for_selection(
                (
                    (PLAN_APPROVE_OPTION_ID,)
                    if result.choice == "epic"
                    else self._approval_selection(
                        result.commit_plan,
                        result.run_coder,
                    )
                ),
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
        if not any(
            option.id == PLAN_APPROVE_OPTION_ID for option in self._gate.options
        ):
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

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        if not self._choice_allowed("epic"):
            return
        self.dismiss(_plan_approval_result_for_choice("epic"))

    def _choice_allowed(self, choice: PlanApprovalChoice) -> bool:
        option_ids = {option.id for option in self._gate.options}
        allowed = (
            PLAN_APPROVE_OPTION_ID in option_ids
            if choice in {"approve", "epic"}
            else {PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID} <= option_ids
        )
        if allowed:
            return True
        self.notify(
            "Choice is not present in this approval request",
            severity="warning",
        )
        return False

    def _has_approval_extras(self) -> bool:
        return any(len(branch) > 1 for branch in self._gate.branches)

    def _selected_approval_flags(self) -> tuple[bool, bool]:
        controls = self.query_one(GateBranchControls)
        branch_index = next(
            index
            for index, branch in enumerate(self._gate.branches)
            if PLAN_APPROVE_OPTION_ID in branch
        )
        selected = set(controls.selected_option_ids(branch_index))
        return (
            PLAN_COMMIT_OPTION_ID in selected,
            PLAN_APPROVE_OPTION_ID in selected,
        )

    @staticmethod
    def _approval_selection(
        commit_plan: bool,
        run_coder: bool,
    ) -> tuple[str, ...]:
        return tuple(
            option_id
            for option_id, selected in (
                (PLAN_APPROVE_OPTION_ID, run_coder),
                (PLAN_COMMIT_OPTION_ID, commit_plan),
            )
            if selected
        )

    def _result_for_selection(
        self,
        selected_option_ids: tuple[str, ...],
        *,
        feedback: str | None = None,
        coder_prompt: str | None = None,
        coder_model: str | None = None,
        option_inputs: Mapping[str, dict[str, Any]] | None = None,
    ) -> PlanApprovalResult:
        selected = set(selected_option_ids)
        resolved_inputs = option_inputs or {}
        if selected_option_ids == ("reject",):
            return PlanApprovalResult(
                action="reject",
                selected_option_ids=selected_option_ids,
                option_inputs=resolved_inputs,
            )
        if selected_option_ids == ("feedback",):
            return PlanApprovalResult(
                action="reject",
                feedback=feedback,
                selected_option_ids=selected_option_ids,
                option_inputs=resolved_inputs,
            )
        epic = self._default_choice == "epic"
        return PlanApprovalResult(
            action="epic" if epic else "approve",
            commit_plan=epic or PLAN_COMMIT_OPTION_ID in selected,
            run_coder=epic or PLAN_APPROVE_OPTION_ID in selected,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            choice=(
                "epic"
                if epic
                else "tale"
                if selected == {PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID}
                else "approve"
                if selected == {PLAN_APPROVE_OPTION_ID}
                else None
            ),
            selected_option_ids=selected_option_ids,
            option_inputs=resolved_inputs,
        )

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

    def action_feedback(self) -> None:
        """Dismiss modal and request feedback via PromptInputBar."""
        self.dismiss(PlanApprovalResult(action="feedback_requested"))
