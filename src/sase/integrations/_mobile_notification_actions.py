"""Host-side action execution for mobile notification bridge rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.integrations._mobile_notification_models import (
    MobileNotificationBridgeRow,
    MobilePlanActionError,
    MobilePlanActionResult,
)
from sase.integrations._mobile_notification_snapshot import (
    resolve_mobile_notification_detail,
)
from sase.integrations._mobile_notification_side_effects import (
    dismiss_notification_best_effort,
)
from sase.launch_approval_actions import (
    LaunchApprovalActionContext,
    LaunchApprovalActionError,
    execute_launch_approval_response,
)
from sase.plan_approval_actions import (
    PLAN_APPROVAL_ACTIONS,
    PlanApprovalActionContext,
    PlanApprovalActionError,
    execute_plan_approval_response,
)


def execute_mobile_plan_action(
    prefix: str,
    choice: str,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
) -> MobilePlanActionResult:
    """Write a plan approval response and run best-effort host side effects."""
    from sase.notifications.pending_actions import resolve_prefix

    identity = resolve_prefix(prefix)
    if identity.resolution == "missing":
        raise MobilePlanActionError("not_found", prefix, "action prefix not found")
    if identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise MobilePlanActionError(
            "ambiguous_prefix", prefix, "action prefix is ambiguous"
        )

    notification = resolve_mobile_notification_detail(identity.notification_id)
    if notification is None:
        raise MobilePlanActionError(
            "not_found", identity.notification_id, "notification not found"
        )
    if notification.action not in PLAN_APPROVAL_ACTIONS:
        raise MobilePlanActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a plan approval",
        )
    if notification.action_state == "already_handled":
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "action already handled",
        )
    if notification.action_state == "stale":
        raise MobilePlanActionError("gone_stale", notification.id, "action is stale")
    if notification.action_state in {"missing_request", "missing_target"}:
        raise MobilePlanActionError(
            "invalid_request", notification.id, f"action is {notification.action_state}"
        )

    from sase.notification_gates.paths import resolve_action_bundle

    bundle = resolve_action_bundle(
        notification.action,
        notification.host_action_data,
    )
    if bundle is None or not bundle.root.is_dir():
        raise MobilePlanActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    if not bundle.request.is_file():
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "plan request was already consumed",
        )
    if not notification.host_files:
        raise MobilePlanActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )

    try:
        action_result = execute_plan_approval_response(
            PlanApprovalActionContext(
                id=notification.id,
                host_files=tuple(notification.host_files),
                host_action_data=dict(notification.host_action_data),
            ),
            choice,
            feedback=feedback,
            commit_plan=commit_plan,
            run_coder=run_coder,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
        )
    except PlanApprovalActionError as exc:
        raise MobilePlanActionError(exc.code, exc.target, str(exc)) from exc
    return MobilePlanActionResult(
        prefix=prefix,
        notification_id=notification.id,
        response_file=action_result.response_file,
        response_json=action_result.response_json,
        message=action_result.message,
    )


def execute_mobile_hitl_action(
    prefix: str,
    choice: str,
    *,
    feedback: str | None = None,
) -> MobilePlanActionResult:
    """Write a workflow HITL response and dismiss the notification."""
    notification = _resolve_action_notification(prefix, "HITL")
    artifacts_dir = Path(
        notification.host_action_data.get("artifacts_dir", "")
    ).expanduser()
    if not artifacts_dir.is_dir():
        raise MobilePlanActionError(
            "invalid_request", "artifacts_dir", "artifacts_dir is missing"
        )
    if not (artifacts_dir / "hitl_request.json").is_file():
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "HITL request was already consumed",
        )

    response_json, message = _hitl_response_json(choice, feedback=feedback)
    response_path = artifacts_dir / "hitl_response.json"
    _write_json_once(response_path, response_json, notification.id)
    dismiss_notification_best_effort(notification.id)
    return MobilePlanActionResult(
        prefix=prefix,
        notification_id=notification.id,
        response_file="hitl_response.json",
        response_json=response_json,
        message=message,
    )


def execute_mobile_question_action(
    prefix: str,
    choice: str,
    *,
    question_index: int | None = None,
    selected_option_id: str | None = None,
    selected_option_label: str | None = None,
    selected_option_index: int | None = None,
    custom_answer: str | None = None,
    global_note: str | None = None,
) -> MobilePlanActionResult:
    """Execute a complete user-question form through the shared gate path."""
    notification = _resolve_action_notification(prefix, "UserQuestion")
    from sase.user_question_actions import (
        UserQuestionActionContext,
        UserQuestionActionError,
        execute_user_question_response,
        read_user_question_request,
    )

    context = UserQuestionActionContext(
        notification_id=notification.id,
        host_action_data=dict(notification.host_action_data),
    )
    response_dir = Path(
        notification.host_action_data.get("response_dir", "")
    ).expanduser()
    if not response_dir.is_dir():
        raise MobilePlanActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    try:
        request_data = read_user_question_request(response_dir)
    except UserQuestionActionError as exc:
        raise MobilePlanActionError(exc.code, exc.target, str(exc)) from exc

    response_json = _question_response_json(
        request_data,
        choice,
        question_index=question_index,
        selected_option_id=selected_option_id,
        selected_option_label=selected_option_label,
        selected_option_index=selected_option_index,
        custom_answer=custom_answer,
        global_note=global_note,
    )
    try:
        result = execute_user_question_response(
            context,
            response_json,
            source="mobile",
        )
    except UserQuestionActionError as exc:
        raise MobilePlanActionError(exc.code, exc.target, str(exc)) from exc
    return MobilePlanActionResult(
        prefix=prefix,
        notification_id=notification.id,
        response_file=result.response_file,
        response_json=result.response_json,
        message=result.message,
    )


def execute_mobile_launch_action(
    prefix: str,
    choice: str,
    *,
    feedback: str | None = None,
) -> MobilePlanActionResult:
    """Write a launch approval response and dismiss the notification."""
    notification = _resolve_action_notification(prefix, "LaunchApproval")
    try:
        action_result = execute_launch_approval_response(
            LaunchApprovalActionContext(
                id=notification.id,
                host_files=tuple(notification.host_files),
                host_action_data=dict(notification.host_action_data),
            ),
            choice,
            feedback=feedback,
        )
    except LaunchApprovalActionError as exc:
        raise MobilePlanActionError(exc.code, exc.target, str(exc)) from exc
    return MobilePlanActionResult(
        prefix=prefix,
        notification_id=notification.id,
        response_file=action_result.response_file,
        response_json=action_result.response_json,
        message=action_result.message,
    )


def _resolve_action_notification(
    prefix: str,
    expected_action: str,
) -> MobileNotificationBridgeRow:
    from sase.notifications.pending_actions import resolve_prefix

    identity = resolve_prefix(prefix)
    if identity.resolution == "missing":
        raise MobilePlanActionError("not_found", prefix, "action prefix not found")
    if identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise MobilePlanActionError(
            "ambiguous_prefix", prefix, "action prefix is ambiguous"
        )

    notification = resolve_mobile_notification_detail(identity.notification_id)
    if notification is None:
        raise MobilePlanActionError(
            "not_found", identity.notification_id, "notification not found"
        )
    if notification.action != expected_action:
        raise MobilePlanActionError(
            "unsupported_action",
            notification.action or "non_action",
            f"notification is not {expected_action}",
        )
    if notification.action_state == "already_handled":
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "action already handled",
        )
    if notification.action_state == "stale":
        raise MobilePlanActionError("gone_stale", notification.id, "action is stale")
    if notification.action_state in {"missing_request", "missing_target"}:
        raise MobilePlanActionError(
            "invalid_request", notification.id, f"action is {notification.action_state}"
        )
    return notification


def _hitl_response_json(
    choice: str,
    *,
    feedback: str | None,
) -> tuple[dict[str, Any], str]:
    if choice == "accept":
        return {"action": "accept", "approved": True}, "HITL accepted"
    if choice == "reject":
        return {"action": "reject", "approved": False}, "HITL rejected"
    if choice == "feedback":
        if not feedback:
            raise MobilePlanActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return (
            {"action": "feedback", "approved": False, "feedback": feedback},
            "HITL feedback received",
        )
    raise MobilePlanActionError(
        "unsupported_action", choice, "unsupported HITL action choice"
    )


def _question_response_json(
    request_data: dict[str, Any],
    choice: str,
    *,
    question_index: int | None,
    selected_option_id: str | None,
    selected_option_label: str | None,
    selected_option_index: int | None,
    custom_answer: str | None,
    global_note: str | None,
) -> dict[str, Any]:
    questions = request_data.get("questions")
    if not isinstance(questions, list):
        raise MobilePlanActionError(
            "invalid_request", "questions", "question_request.json missing questions"
        )
    index = question_index or 0
    try:
        question = questions[index]
    except IndexError as exc:
        raise MobilePlanActionError(
            "invalid_request", "question_index", "question index is not available"
        ) from exc
    if not isinstance(question, dict):
        raise MobilePlanActionError(
            "invalid_request", "question", "question entry is malformed"
        )

    if choice == "answer":
        selected = [
            _resolve_question_option_label(
                question,
                selected_option_id=selected_option_id,
                selected_option_label=selected_option_label,
                selected_option_index=selected_option_index,
            )
        ]
        custom_feedback = None
    elif choice == "custom":
        if custom_answer is None:
            raise MobilePlanActionError(
                "invalid_request", "custom_answer", "custom answer is required"
            )
        selected = []
        custom_feedback = custom_answer
    else:
        raise MobilePlanActionError(
            "unsupported_action", choice, "unsupported question action choice"
        )

    return {
        "answers": [
            {
                "question": str(question.get("question", "")),
                "selected": selected,
                "custom_feedback": custom_feedback,
            }
        ],
        "global_note": global_note or "",
    }


def _resolve_question_option_label(
    question: dict[str, Any],
    *,
    selected_option_id: str | None,
    selected_option_label: str | None,
    selected_option_index: int | None,
) -> str:
    if selected_option_label is not None:
        return selected_option_label
    options = question.get("options")
    if not isinstance(options, list):
        raise MobilePlanActionError(
            "invalid_request", "options", "question is missing options"
        )
    option: Any
    if selected_option_id is not None:
        for option in options:
            if isinstance(option, dict) and option.get("id") == selected_option_id:
                label = option.get("label")
                if isinstance(label, str):
                    return label
        raise MobilePlanActionError(
            "invalid_request",
            "selected_option_id",
            "question option id is not available",
        )
    if selected_option_index is None:
        raise MobilePlanActionError(
            "invalid_request",
            "selected_option",
            "question answer requires a selected option",
        )
    try:
        option = options[selected_option_index]
    except IndexError as exc:
        raise MobilePlanActionError(
            "invalid_request",
            "selected_option_index",
            "question option index is not available",
        ) from exc
    if isinstance(option, dict) and isinstance(option.get("label"), str):
        return option["label"]
    raise MobilePlanActionError(
        "invalid_request", "label", "question option is missing a label"
    )


def _write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str,
) -> None:
    try:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise MobilePlanActionError(
            "conflict_already_handled", notification_id, "response already exists"
        ) from exc
