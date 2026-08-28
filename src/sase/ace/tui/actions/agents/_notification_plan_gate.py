"""Neutral plan gate loading and response execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_plan_response import (
    plan_approval_choice_for_status,
    request_agents_after_plan_response,
)
from sase.plan_approval_choices import PlanApprovalModalChoice

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification

    from ...models import Agent
    from ...modals import GateBranchData, PlanApprovalResult
    from ...modals.gate_action_controls import GateActionsData


@dataclass(frozen=True)
class PlanGateModalLoad:
    """Worker-loaded data needed to compose a neutral plan gate."""

    plan_file: str
    plan_content: str
    default_choice: PlanApprovalModalChoice
    gate: GateBranchData
    actions: GateActionsData
    bundle: ResolvedGateBundle


def load_neutral_plan_modal_data(
    notification: Notification,
) -> PlanGateModalLoad:
    """Verify a v2 plan bundle and read its display content off the UI thread."""
    if not notification.files:
        raise RuntimeError("plan file is missing")
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.paths import resolve_notification_bundle

    from ._notification_gate_actions import load_gate_actions
    from ...modals import GateBranchData

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        raise RuntimeError("notification does not reference a neutral plan gate")
    envelope, _adapter = load_and_verify_bundle(bundle.root)
    kind = envelope.get("kind")
    default_choice: PlanApprovalModalChoice = "epic" if kind == "epic_plan" else "tale"
    plan_file = notification.files[0]
    plan_content = Path(plan_file).expanduser().read_text(encoding="utf-8")
    return PlanGateModalLoad(
        plan_file=plan_file,
        plan_content=plan_content,
        default_choice=default_choice,
        gate=GateBranchData.from_envelope(envelope),
        actions=load_gate_actions(bundle.root, dict(envelope)),
        bundle=bundle,
    )


def submit_neutral_plan_response(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
) -> bool:
    """Execute a neutral plan choice as tracked background work."""
    choice = result.choice or plan_approval_choice_for_status(result)
    if choice is None:
        choice = "feedback" if result.feedback else "reject"

    submit = getattr(app, "_submit_session_worker", None)
    if not callable(submit):
        app.notify("Plan execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    from ...actions.proc_actions import TrackedProcResult
    from sase.main.plan_pending import plan_context_from_notification
    from sase.plan_approval_actions import execute_plan_approval_response

    def work() -> TrackedProcResult[object]:
        try:
            action_result = execute_plan_approval_response(
                plan_context_from_notification(notification),
                choice,
                feedback=result.feedback,
                commit_plan=result.commit_plan,
                run_coder=result.run_coder,
                coder_prompt=result.coder_prompt,
                coder_model=result.coder_model,
                epic_launch_mode="launch",
                epic_launch_origin="ace",
                option_inputs=result.option_inputs or None,
            )
        except Exception as exc:
            return TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        return TrackedProcResult(
            success=True,
            message=action_result.message,
            payload=action_result,
        )

    def on_complete(completion: object) -> None:
        if not getattr(completion, "success", False):
            app.notify(  # type: ignore[attr-defined]
                getattr(completion, "message", "Plan command failed"),
                severity="error",
            )
            return
        if agent is not None:
            if result.action == "reject" and result.feedback is None:
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                request_agents_after_plan_response(app, agent)
        app._refresh_notification_count()  # type: ignore[attr-defined]

    cl_name = (
        notification.action_data.get("agent_cl_name")
        or Path(notification.files[0]).stem
    )
    project_file = notification.action_data.get("agent_project_file") or (
        notification.action_data.get("project_dir") or notification.files[0]
    )
    submit(
        "plan-gate",
        work,
        display_name=f"Plan response: {choice}",
        cl_name=str(cl_name),
        project_file=str(project_file),
        on_complete=on_complete,
    )
    return True
