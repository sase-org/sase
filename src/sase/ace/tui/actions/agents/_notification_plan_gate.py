"""Neutral plan gate loading and response execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_plan_response import (
    plan_approval_choice_for_status,
    plan_approval_status,
    refresh_agents_from_cache,
)
from sase.plan_approval_choices import PlanApprovalModalChoice

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification

    from ...models import Agent
    from ...modals import GateBranchData, PlanApprovalResult


@dataclass(frozen=True)
class PlanGateModalLoad:
    """Worker-loaded data needed to compose a neutral plan gate."""

    plan_file: str
    plan_content: str
    default_choice: PlanApprovalModalChoice
    gate: GateBranchData
    bundle: ResolvedGateBundle


def load_neutral_plan_modal_data(
    notification: Notification,
) -> PlanGateModalLoad:
    """Verify a v2 plan bundle and read its display content off the UI thread."""
    if not notification.files:
        raise RuntimeError("plan file is missing")
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.paths import resolve_notification_bundle

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
    host_owns_epic_launch = False
    if choice == "epic":
        from sase.plan_approval_actions import (
            PlanApprovalValidationError,
            require_plan_approval_validation,
        )

        try:
            validation = require_plan_approval_validation(notification.files[0], "epic")
        except PlanApprovalValidationError as exc:
            app.notify(  # type: ignore[attr-defined]
                str(exc),
                title="Epic approval blocked",
                severity="error",
                timeout=15,
            )
            return False
        from ._notification_epic_launch import submit_epic_launch_task

        host_owns_epic_launch = submit_epic_launch_task(
            app,
            notification,
            plan_file=notification.files[0],
            phase_count=len(validation.plan.phases) if validation.plan else 0,
        )

    submit = getattr(app, "_submit_tracked_task", None)
    if not callable(submit):
        app.notify("Tracked plan execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    from ...actions.task_actions import TrackedTaskResult
    from sase.main.plan_pending import plan_context_from_notification
    from sase.plan_approval_actions import execute_plan_approval_response

    def work() -> TrackedTaskResult[object]:
        try:
            action_result = execute_plan_approval_response(
                plan_context_from_notification(notification),
                choice,
                feedback=result.feedback,
                commit_plan=result.commit_plan,
                run_coder=result.run_coder,
                coder_prompt=result.coder_prompt,
                coder_model=result.coder_model,
                epic_launch_mode=("skip" if host_owns_epic_launch else "detached"),
            )
        except Exception as exc:
            return TrackedTaskResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        return TrackedTaskResult(
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
                app._agent_pre_question_status.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                status = plan_approval_status(result)
                if status is None and result.feedback is not None:
                    status = "RUNNING"
                if status is not None:
                    app._agent_status_overrides[agent.identity] = status  # type: ignore[attr-defined]
                    refresh_agents_from_cache(app, agent)
        app._refresh_notification_count()  # type: ignore[attr-defined]

    cl_name = (
        notification.action_data.get("agent_cl_name")
        or Path(notification.files[0]).stem
    )
    project_file = notification.action_data.get("agent_project_file") or (
        notification.action_data.get("project_dir") or notification.files[0]
    )
    submitted = submit(
        "plan-gate",
        cl_name,
        project_file,
        work,
        display_name=f"Plan response: {choice}",
        dedup_key=f"plan-gate:{notification.id}",
        duplicate_message="This plan response is already running",
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    return submitted is not None
