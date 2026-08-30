"""Result models and selection-to-protocol mapping for plan approval.

What a reviewer's decision *means* — which protocol action gets written, whether
the plan is committed, whether a coder follows — is a pure function of the
selected option ids and the gate's tier. Owning that mapping here lets
:class:`~sase.ace.tui.modals.plan_approval_modal.PlanApprovalModal` deal in
widgets and keys instead of protocol fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.plan_approval_choices import (
    PlanApprovalModalChoice as PlanApprovalChoice,
    PlanApprovalProtocolFields,
    approval_protocol_for_choice as _approval_protocol_for_choice,
)
from sase.plan_gate import PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID


@dataclass
class PlanApprovalResult:
    """Result from the plan approval modal."""

    action: str  # "approve", "reject", "epic", "feedback_requested", or "approve_prompt_edit"
    feedback: str | None = None
    commit_plan: bool = True
    run_coder: bool = True
    coder_prompt: str | None = None
    coder_model: str | None = None
    wait_spec: str | None = None
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
    wait_spec: str | None = None
    choice: PlanApprovalChoice | None = None


def approval_protocol_for_choice(
    choice: PlanApprovalChoice,
) -> PlanApprovalProtocolFields:
    """Map a product-level approval choice to the existing response protocol."""
    return _approval_protocol_for_choice(choice)


def approval_selection_option_ids(
    commit_plan: bool,
    run_coder: bool,
) -> tuple[str, ...]:
    """Return the option ids an approve/commit flag pair selects, in gate order."""
    return tuple(
        option_id
        for option_id, selected in (
            (PLAN_APPROVE_OPTION_ID, run_coder),
            (PLAN_COMMIT_OPTION_ID, commit_plan),
        )
        if selected
    )


def plan_approval_result_for_choice(
    choice: PlanApprovalChoice,
    *,
    feedback: str | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    wait_spec: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
) -> PlanApprovalResult:
    """Build a modal result for a product-level approval choice."""
    protocol = approval_protocol_for_choice(choice)
    effective_commit = protocol.commit_plan if commit_plan is None else commit_plan
    effective_run = protocol.run_coder if run_coder is None else run_coder
    selected_option_ids = (
        (PLAN_APPROVE_OPTION_ID,)
        if choice == "epic"
        else approval_selection_option_ids(effective_commit, effective_run)
    )
    return PlanApprovalResult(
        action=protocol.action,
        feedback=feedback,
        commit_plan=effective_commit,
        run_coder=effective_run,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        wait_spec=wait_spec,
        choice=choice,
        selected_option_ids=selected_option_ids,
    )


def plan_approval_result_for_selection(
    selected_option_ids: tuple[str, ...],
    *,
    epic: bool,
    feedback: str | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    wait_spec: str | None = None,
    option_inputs: Mapping[str, dict[str, Any]] | None = None,
) -> PlanApprovalResult:
    """Build a modal result for the option ids a reviewer actually submitted."""
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
    return PlanApprovalResult(
        action="epic" if epic else "approve",
        commit_plan=epic or PLAN_COMMIT_OPTION_ID in selected,
        run_coder=epic or PLAN_APPROVE_OPTION_ID in selected,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        wait_spec=wait_spec,
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


__all__ = [
    "PendingApproveState",
    "PlanApprovalChoice",
    "PlanApprovalResult",
    "approval_protocol_for_choice",
    "approval_selection_option_ids",
    "plan_approval_result_for_choice",
    "plan_approval_result_for_selection",
]
