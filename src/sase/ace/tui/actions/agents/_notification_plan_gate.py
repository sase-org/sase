"""Neutral plan gate loading and response execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import GATE_ANSWER
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

    durable_submitted = _submit_durable_neutral_plan_response(
        app,
        notification,
        agent,
        result,
        choice,
    )
    if durable_submitted is not None:
        return durable_submitted

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
                wait=result.wait_spec,
                capacity=result.capacity,
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


def _submit_durable_neutral_plan_response(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
    choice: PlanApprovalModalChoice | str,
) -> bool | None:
    """Submit a neutral plan response through ACE's durable proc queue."""
    submit = getattr(app, "_submit_durable_proc", None)
    if not callable(submit):
        return None

    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        return None

    request_id = str(notification.action_data.get("request_id") or notification.id)
    request_kind = str(notification.action_data.get("request_kind") or bundle.kind)
    selected_option_ids, input_data, per_option_inputs = _plan_gate_submission_payload(
        notification,
        result,
        choice,
    )

    def on_complete(completion: object) -> None:
        if not getattr(completion, "success", False):
            app.notify(  # type: ignore[attr-defined]
                getattr(completion, "message", "Plan command failed"),
                severity="error",
            )
            _refresh_notifications(app)
            return
        if agent is not None:
            if result.action == "reject" and result.feedback is None:
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                request_agents_after_plan_response(app, agent)
        _refresh_notifications(app)

    cl_name = str(
        notification.action_data.get("agent_cl_name")
        or (Path(notification.files[0]).stem if notification.files else request_id)
    )
    project_file = str(
        notification.action_data.get("agent_project_file")
        or notification.action_data.get("project_dir")
        or (notification.files[0] if notification.files else bundle.root)
    )

    task = submit(
        sase_argv(
            "gate",
            "answer",
            "--id",
            request_id,
            "--kind",
            request_kind,
            "--no-detach",
            "--json",
        ),
        operation=GATE_ANSWER,
        request=durable_request_payload(
            feedback=result.feedback,
            input_data=None if per_option_inputs is not None else input_data,
            option_ids=list(selected_option_ids),
            option_inputs=per_option_inputs,
            source="tui",
        ),
        request_fingerprint=durable_fingerprint(
            GATE_ANSWER,
            request_kind,
            request_id,
            ",".join(selected_option_ids),
            "tui",
        ),
        concurrency_keys=(f"notification-gate:{notification.id}",),
        label=f"Plan response: {choice}",
        display_name=f"Plan response: {choice}",
        cl_name=cl_name,
        project_file=project_file,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    if task is None:
        return False

    from ._notification_utils import schedule_gate_decision_receipt_refresh

    schedule_gate_decision_receipt_refresh(
        app,
        notification=notification,
        bundle_path=bundle.root,
        agent=agent,
    )
    return True


def _plan_gate_submission_payload(
    notification: Notification,
    result: PlanApprovalResult,
    choice: PlanApprovalModalChoice | str,
) -> tuple[tuple[str, ...], dict[str, object], dict[str, object] | None]:
    """Return gate.answer option ids and input payload for one plan result."""
    from sase.plan_approval_choices import plan_approval_selection_for_choice

    tier: Literal["tale", "epic"] = (
        "epic"
        if notification.action == "EpicApproval"
        or notification.action_data.get("request_kind") == "epic_plan"
        else "tale"
    )
    selected_option_ids = result.selected_option_ids
    if not selected_option_ids:
        selected_option_ids = plan_approval_selection_for_choice(
            str(choice),
            tier=tier,
            commit_plan=result.commit_plan,
            run_coder=result.run_coder,
        )

    input_data: dict[str, object] = {}
    if result.feedback is not None:
        input_data["feedback"] = result.feedback
    if "approve" in selected_option_ids and tier == "tale":
        if result.coder_prompt is not None:
            input_data["coder_prompt"] = result.coder_prompt
        if result.coder_model is not None:
            input_data["coder_model"] = result.coder_model
    if result.wait_spec is not None and any(
        option_id in selected_option_ids for option_id in ("approve", "commit")
    ):
        input_data["wait"] = result.wait_spec
    if tier == "epic" and selected_option_ids == ("approve",):
        input_data["epic_launch_mode"] = "launch"
        if result.capacity is not None:
            input_data["capacity"] = result.capacity

    per_option_inputs: dict[str, object] | None = None
    if result.option_inputs and any(result.option_inputs.values()):
        per_option_inputs = {
            option_id: {
                **input_data,
                **dict(result.option_inputs.get(option_id, {})),
            }
            for option_id in selected_option_ids
        }
    return selected_option_ids, input_data, per_option_inputs


def _refresh_notifications(app: object) -> None:
    schedule_refresh = getattr(app, "_schedule_notification_snapshot_refresh", None)
    if callable(schedule_refresh):
        schedule_refresh()
        return
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()
