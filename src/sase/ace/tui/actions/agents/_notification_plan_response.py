"""Plan approval response encoding and persisted action helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._notification_utils import (
    request_notification_agents_refresh,
)
from sase.plan_approval_choices import (
    approval_choice_persist_action,
    approval_protocol_for_choice,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import PlanApprovalResult


def build_plan_approval_response(
    result: PlanApprovalResult,
    *,
    epic_launch_owner: Literal["host"] | None = None,
) -> dict[str, object]:
    """Build the JSON response for a plan approval modal result."""
    action, commit_plan, run_coder = plan_approval_protocol_fields(result)
    response_data: dict[str, object] = {
        "action": action,
    }
    if result.feedback is not None:
        response_data["feedback"] = result.feedback
    response_data["commit_plan"] = commit_plan
    response_data["run_coder"] = run_coder
    if result.coder_prompt is not None:
        response_data["coder_prompt"] = result.coder_prompt
    if result.coder_model is not None:
        response_data["coder_model"] = result.coder_model
    if action == "epic" and epic_launch_owner is not None:
        response_data["epic_launch_owner"] = epic_launch_owner
    return response_data


def plan_approval_protocol_fields(
    result: PlanApprovalResult,
) -> tuple[str, bool, bool]:
    """Return runner-facing action, commit flag, and coder flag."""
    if result.choice == "approve":
        return "approve", result.commit_plan, result.run_coder
    if result.choice is not None:
        protocol = approval_protocol_for_choice(result.choice)
        return protocol.action, protocol.commit_plan, protocol.run_coder

    if result.action == "epic":
        return result.action, True, True

    return result.action, result.commit_plan, result.run_coder


def plan_approval_persist_action(result: PlanApprovalResult) -> str | None:
    """Return the persisted plan action marker for a result, if any."""
    choice = plan_approval_choice_for_status(result)
    return None if choice is None else approval_choice_persist_action(choice)


def plan_approval_choice_for_status(result: PlanApprovalResult) -> str | None:
    """Infer the product-level approval choice for persisted action metadata."""
    if result.choice in {"tale", "epic"}:
        return result.choice
    if result.action == "approve" and result.commit_plan and not result.run_coder:
        return "commit"
    if result.action == "approve" and result.commit_plan and result.run_coder:
        return "tale"
    if result.action == "approve" and not result.commit_plan and result.run_coder:
        return "approve"
    if result.action == "approve" and not result.commit_plan and not result.run_coder:
        return "approve"
    if result.action == "epic":
        return result.action
    return None


def request_agents_after_plan_response(app: object, agent: Agent | None = None) -> None:
    """Request a bounded reload after a plan response updates gate state on disk."""
    request_notification_agents_refresh(app, agent=agent)
