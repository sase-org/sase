"""Decision handling for the plan approval modal.

Everything that turns a reviewer's action into a
:class:`~sase.ace.tui.modals.plan_approval_results.PlanApprovalResult` lives
here: the branch-resolution handler, the backward-compatible programmatic
choice actions, and the coder-options round trip behind the ``c`` key. That
leaves :class:`~sase.ace.tui.modals.plan_approval_modal.PlanApprovalModal`
owning layout, scrolling, and copying.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.plan_gate import PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID

from .gate_branch_controls import GateBranchControls, GateBranchData
from .plan_approval_results import (
    PlanApprovalChoice,
    PlanApprovalResult,
    approval_selection_option_ids,
    plan_approval_result_for_choice,
    plan_approval_result_for_selection,
)


class PlanApprovalDecisionsMixin:
    """Turn plan-review actions into modal results.

    The mixin reads the gate model and the mounted branch controls the modal
    already owns; it never renders anything of its own.
    """

    _gate: GateBranchData
    _default_choice: PlanApprovalChoice
    _llm_provider: str | None
    _plan_file: str

    # -- branch submission -------------------------------------------------

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        event.stop()
        self.dismiss(  # type: ignore[attr-defined]
            self._result_for_selection(
                event.selected_option_ids,
                feedback=event.feedback,
                option_inputs=event.option_inputs,
            )
        )

    def _result_for_selection(
        self,
        selected_option_ids: tuple[str, ...],
        *,
        feedback: str | None = None,
        coder_prompt: str | None = None,
        coder_model: str | None = None,
        wait_spec: str | None = None,
        option_inputs: Mapping[str, dict[str, Any]] | None = None,
    ) -> PlanApprovalResult:
        return plan_approval_result_for_selection(
            selected_option_ids,
            epic=self._default_choice == "epic",
            feedback=feedback,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait_spec=wait_spec,
            option_inputs=option_inputs,
        )

    # -- programmatic choice actions ---------------------------------------

    def action_approve(self) -> None:
        """Backward-compatible programmatic plain-approval action."""
        if not self._choice_allowed("approve"):
            return
        self.dismiss(plan_approval_result_for_choice("approve"))  # type: ignore[attr-defined]

    def action_approve_default(self) -> None:
        """Backward-compatible alias for submitting the active branch."""
        self.action_submit_branch()  # type: ignore[attr-defined]

    def action_tale(self) -> None:
        """Backward-compatible programmatic tale selection."""
        if not self._choice_allowed("tale"):
            return
        self.dismiss(plan_approval_result_for_choice("tale"))  # type: ignore[attr-defined]

    def action_reject(self) -> None:
        """Reject the plan without feedback."""
        self.dismiss(PlanApprovalResult(action="reject"))  # type: ignore[attr-defined]

    def action_epic(self) -> None:
        """Create an epic from the plan."""
        if not self._choice_allowed("epic"):
            return
        self.dismiss(plan_approval_result_for_choice("epic"))  # type: ignore[attr-defined]

    def action_feedback(self) -> None:
        """Dismiss modal and request feedback via PromptInputBar."""
        self.dismiss(PlanApprovalResult(action="feedback_requested"))  # type: ignore[attr-defined]

    def _choice_allowed(self, choice: PlanApprovalChoice) -> bool:
        option_ids = {option.id for option in self._gate.options}
        allowed = (
            PLAN_APPROVE_OPTION_ID in option_ids
            if choice in {"approve", "epic"}
            else {PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID} <= option_ids
        )
        if allowed:
            return True
        self.notify(  # type: ignore[attr-defined]
            "Choice is not present in this approval request",
            severity="warning",
        )
        return False

    # -- coder options round trip ------------------------------------------

    def action_custom(self) -> None:
        """Open the custom approval modal."""
        if not any(
            option.id == PLAN_APPROVE_OPTION_ID for option in self._gate.options
        ):
            self.notify(  # type: ignore[attr-defined]
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

    def _push_approve_options(
        self,
        commit_plan: bool = True,
        run_coder: bool = True,
        coder_prompt: str = "",
        coder_model: str | None = None,
        wait_spec: str | None = None,
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
                self.dismiss(  # type: ignore[attr-defined]
                    PlanApprovalResult(
                        action="approve_prompt_edit",
                        commit_plan=result.commit_plan,
                        run_coder=result.run_coder,
                        coder_prompt=result.coder_prompt,
                        coder_model=result.coder_model,
                        wait_spec=result.wait_spec,
                        choice=result.choice,
                        selected_option_ids=approval_selection_option_ids(
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
                    else approval_selection_option_ids(
                        result.commit_plan,
                        result.run_coder,
                    )
                ),
                coder_prompt=result.coder_prompt,
                coder_model=result.coder_model,
                wait_spec=result.wait_spec,
            )
            self.dismiss(approval_result)  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ApproveOptionsModal(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
                coder_model=coder_model,
                wait_spec=wait_spec,
                choice=choice,
                plan_file=self._plan_file,
                planner_llm_provider=self._llm_provider,
            ),
            on_options_dismiss,
        )

    def _has_approval_extras(self) -> bool:
        return any(len(branch) > 1 for branch in self._gate.branches)

    def _selected_approval_flags(self) -> tuple[bool, bool]:
        controls = self.query_one(GateBranchControls)  # type: ignore[attr-defined]
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


__all__ = ["PlanApprovalDecisionsMixin"]
