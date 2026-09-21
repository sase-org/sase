"""Neutral gate-response execution and plan-response file helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase._plan_approval_protocol import EpicLaunchMode
from sase._plan_approval_protocol import PlanApprovalActionContext
from sase._plan_approval_protocol import PlanApprovalActionError
from sase._plan_approval_protocol import PlanApprovalActionResult
from sase._plan_approval_protocol import resolve_plan_approval_choice
from sase.plan_approval_choices import plan_approval_response_message_for_selection
from sase.plan_approval_choices import plan_approval_selection_for_choice

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin, EpicLaunchSubmission
    from sase.xprompt.directive_edit import PromptWaitDirective


def execute_neutral_plan_approval_response(
    notification: PlanApprovalActionContext,
    bundle_path: Path,
    choice: str | None,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    wait: str | None,
    wait_spec: PromptWaitDirective | None,
    capacity: int | None,
    epic_launch_mode: EpicLaunchMode,
    epic_launch_origin: EpicLaunchOrigin,
    option_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PlanApprovalActionResult:
    """Execute one selected option set through the shared gate executor."""
    if not notification.host_files:
        raise PlanApprovalActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )
    resolved_choice = resolve_plan_approval_choice(notification.host_files[0], choice)
    selection_choice = (
        "feedback"
        if resolved_choice == "reject" and feedback is not None
        else resolved_choice
    )
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateError

    try:
        envelope, _adapter = load_and_verify_bundle(bundle_path)
    except GateError as exc:
        raise PlanApprovalActionError(exc.code, exc.target, str(exc)) from exc
    tier: Literal["tale", "epic"] = (
        "epic" if envelope.get("kind") == "epic_plan" else "tale"
    )
    from sase.gate_shell.log import bind_gate_shell_execution_callbacks
    from sase.gate_shell.settlement import settle_gate_shell
    from sase.gate_shell.store import find_gate_shell_by_gate_id

    shell_backed = isinstance(envelope.get("shell"), dict)
    gate_shell = (
        find_gate_shell_by_gate_id(None, str(envelope.get("request_id") or ""))
        if shell_backed
        else None
    )
    execution_kwargs: dict[str, Any] = (
        {}
        if gate_shell is None
        else bind_gate_shell_execution_callbacks(gate_shell.artifacts_dir).as_kwargs()
    )
    try:
        selected_option_ids = plan_approval_selection_for_choice(
            selection_choice,
            tier=tier,
            commit_plan=commit_plan,
            run_coder=run_coder,
        )
    except (KeyError, ValueError) as exc:
        raise PlanApprovalActionError(
            "unsupported_action",
            selection_choice,
            f"unsupported {tier} plan action selection",
        ) from exc

    input_data: dict[str, Any] = {}
    if feedback is not None:
        input_data["feedback"] = feedback
    if "approve" in selected_option_ids and tier == "tale":
        if coder_prompt is not None:
            input_data["coder_prompt"] = coder_prompt
        if coder_model is not None:
            input_data["coder_model"] = coder_model
    if (
        wait_spec is not None
        and wait is not None
        and any(option_id in selected_option_ids for option_id in ("approve", "commit"))
    ):
        input_data["wait"] = wait
    if tier == "epic" and selected_option_ids == ("approve",):
        input_data["epic_launch_mode"] = epic_launch_mode
        if capacity is not None:
            input_data["capacity"] = capacity

    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.paths import RESPONSE_FILENAME

    # `option_inputs` only carries fields a declared-input plan option collects
    # -- none do today (see the ACE gate-inputs phase's deviation note) -- so
    # this branch is inert on landing and every existing call keeps taking the
    # `input_data`-only path below unchanged.
    per_option_inputs = (
        {
            option_id: {**input_data, **dict((option_inputs or {}).get(option_id, {}))}
            for option_id in selected_option_ids
        }
        if option_inputs and any(option_inputs.values())
        else None
    )
    try:
        execution = execute_gate_selection(
            bundle_path,
            selected_option_ids,
            None if per_option_inputs is not None else input_data,
            feedback=feedback,
            source="plan_response",
            epic_launch_origin=epic_launch_origin,
            option_inputs=per_option_inputs,
            **execution_kwargs,
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise PlanApprovalActionError(code, exc.target, str(exc)) from exc
    if gate_shell is not None:
        from sase.notification_gates.decision import (
            read_current_receipt,
            receipt_acceptance_id,
        )
        from sase.notification_gates.failure_outcome import (
            with_follow_up_stage_tracking,
        )

        acceptance_id = receipt_acceptance_id(read_current_receipt(bundle_path))
        with_follow_up_stage_tracking(
            bundle_path,
            acceptance_id=acceptance_id,
            source="plan_response",
            run=lambda: settle_gate_shell(
                gate_shell,
                gate_state="answered",
                reason="plan approval answered",
            ),
        )
    if execution.already_completed:
        raise PlanApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "response already exists",
        )
    from sase.plan_gate import translate_plan_gate_response

    translate_plan_gate_response(bundle_path, execution.response)
    message = plan_approval_response_message_for_selection(
        selected_option_ids, tier=tier
    )
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file=RESPONSE_FILENAME,
        response_path=bundle_path / RESPONSE_FILENAME,
        response_json=execution.response,
        message=message,
        epic_launch_monitor_id=(
            str(execution.response["epic_launch_monitor_id"])
            if execution.response.get("epic_launch_monitor_id")
            else None
        ),
        epic_launch_task_id=(
            str(execution.response["epic_launch_task_id"])
            if execution.response.get("epic_launch_task_id")
            else None
        ),
    )


def parse_plan_approval_wait(wait: str | None) -> PromptWaitDirective | None:
    """Parse a reviewer wait spec before any notification or file mutation."""
    text = wait.strip() if isinstance(wait, str) else None
    if not text:
        return None
    from sase.wait_spec import WaitSpecError, parse_wait_spec

    try:
        return parse_wait_spec(text)
    except WaitSpecError as exc:
        raise PlanApprovalActionError("invalid_request", "wait", str(exc)) from exc


def parse_plan_approval_capacity(capacity: int | None) -> int | None:
    """Validate a reviewer capacity budget before any mutation."""
    if capacity is None:
        return None
    from ._plan_gate_shared import plan_gate_optional_capacity

    try:
        return plan_gate_optional_capacity(capacity)
    except ValueError as exc:
        raise PlanApprovalActionError("invalid_request", "capacity", str(exc)) from exc


def epic_launch_submission_ids(
    launch: EpicLaunchSubmission | None,
) -> tuple[str | None, str | None]:
    if launch is None:
        return None, None
    monitor_id = getattr(launch, "monitor_id", None)
    if monitor_id:
        return str(monitor_id), None
    task_id = getattr(launch, "task_id", None)
    if task_id:
        return None, str(task_id)
    return None, None


def write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str,
) -> None:
    """Write a JSON response without overwriting an existing approval."""
    try:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise PlanApprovalActionError(
            "conflict_already_handled", notification_id, "response already exists"
        ) from exc
