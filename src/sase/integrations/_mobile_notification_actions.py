"""Host-side action execution for mobile notification bridge rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.integrations._mobile_notification_models import (
    MobileGateActionError,
    MobileGateActionResult,
    MobileNotificationBridgeRow,
)
from sase.integrations._mobile_notification_snapshot import (
    resolve_mobile_notification_detail,
)
from sase.integrations._mobile_notification_side_effects import (
    dismiss_notification_best_effort,
)


def _mobile_gate_action_kinds() -> dict[str, str]:
    """Map every selectable gate action to its pending-action kind.

    Derived from the gate registry rather than listed by hand: a hand-kept
    copy silently omits each newly registered kind, which reads on the phone
    as "this notification is not a gate" rather than as a missing entry.
    ``UserQuestion`` is the one deliberate exclusion -- questions have their
    own answer path in this module.
    """
    from sase.notification_gates.adapters import (
        adapter_for_kind,
        registered_gate_kinds,
    )

    adapters = (adapter_for_kind(kind) for kind in registered_gate_kinds())
    return {
        adapter.action: adapter.pending_action_kind
        for adapter in adapters
        if adapter.action != "UserQuestion"
    }


_MOBILE_GATE_ACTION_KINDS = _mobile_gate_action_kinds()


def execute_mobile_gate_action(
    prefix: str,
    selected_option_ids: Sequence[str],
    *,
    feedback: str | None = None,
    option_inputs: Mapping[str, object] | None = None,
) -> MobileGateActionResult:
    """Resolve any non-question mobile gate through the verified executor."""
    notification = _resolve_gate_notification(prefix)
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import RESPONSE_FILENAME, resolve_action_bundle

    bundle = resolve_action_bundle(
        notification.action or "",
        notification.host_action_data,
    )
    if bundle is None or bundle.legacy or not bundle.request.is_file():
        raise MobileGateActionError(
            "invalid_request", "bundle_path", "v2 gate bundle is missing"
        )
    try:
        execution = execute_gate_selection(
            bundle.root,
            selected_option_ids,
            feedback=feedback,
            source="mobile",
            option_inputs=option_inputs,
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"already_answered", "gate_cancelled"}
            else exc.code
        )
        raise MobileGateActionError(code, exc.target, str(exc)) from exc
    if execution.already_completed:
        raise MobileGateActionError(
            "conflict_already_handled",
            notification.id,
            "response already exists",
        )
    dismiss_notification_best_effort(notification.id)
    action = notification.action or ""
    return MobileGateActionResult(
        prefix=prefix,
        notification_id=notification.id,
        action_kind=_MOBILE_GATE_ACTION_KINDS[action],
        response_file=RESPONSE_FILENAME,
        response_json=execution.response,
        message=f"Gate resolved with {', '.join(execution.response['selected_option_ids'])}",
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
) -> MobileGateActionResult:
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
        raise MobileGateActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    try:
        request_data = read_user_question_request(response_dir)
    except UserQuestionActionError as exc:
        raise MobileGateActionError(exc.code, exc.target, str(exc)) from exc

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
        raise MobileGateActionError(exc.code, exc.target, str(exc)) from exc
    return MobileGateActionResult(
        prefix=prefix,
        notification_id=notification.id,
        action_kind="user_question",
        response_file=result.response_file,
        response_json=result.response_json,
        message=result.message,
    )


def _resolve_action_notification(
    prefix: str,
    expected_action: str,
) -> MobileNotificationBridgeRow:
    from sase.notifications.pending_actions import resolve_prefix

    identity = resolve_prefix(prefix)
    if identity.resolution == "missing":
        raise MobileGateActionError("not_found", prefix, "action prefix not found")
    if identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise MobileGateActionError(
            "ambiguous_prefix", prefix, "action prefix is ambiguous"
        )

    notification = resolve_mobile_notification_detail(identity.notification_id)
    if notification is None:
        raise MobileGateActionError(
            "not_found", identity.notification_id, "notification not found"
        )
    if notification.action != expected_action:
        raise MobileGateActionError(
            "unsupported_action",
            notification.action or "non_action",
            f"notification is not {expected_action}",
        )
    if notification.action_state == "already_handled":
        raise MobileGateActionError(
            "conflict_already_handled",
            notification.id,
            "action already handled",
        )
    if notification.action_state == "stale":
        raise MobileGateActionError("gone_stale", notification.id, "action is stale")
    if notification.action_state in {"missing_request", "missing_target"}:
        raise MobileGateActionError(
            "invalid_request", notification.id, f"action is {notification.action_state}"
        )
    return notification


def _resolve_gate_notification(prefix: str) -> MobileNotificationBridgeRow:
    notification = _resolve_action_notification_for_any_kind(prefix)
    if notification.action not in _MOBILE_GATE_ACTION_KINDS:
        raise MobileGateActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a selectable gate",
        )
    return notification


def _resolve_action_notification_for_any_kind(
    prefix: str,
) -> MobileNotificationBridgeRow:
    from sase.notifications.pending_actions import resolve_prefix

    identity = resolve_prefix(prefix)
    if identity.resolution == "missing":
        raise MobileGateActionError("not_found", prefix, "action prefix not found")
    if identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise MobileGateActionError(
            "ambiguous_prefix", prefix, "action prefix is ambiguous"
        )
    notification = resolve_mobile_notification_detail(identity.notification_id)
    if notification is None:
        raise MobileGateActionError(
            "not_found", identity.notification_id, "notification not found"
        )
    if notification.action_state == "already_handled":
        raise MobileGateActionError(
            "conflict_already_handled", notification.id, "action already handled"
        )
    if notification.action_state == "stale":
        raise MobileGateActionError("gone_stale", notification.id, "action is stale")
    if notification.action_state in {"missing_request", "missing_target"}:
        raise MobileGateActionError(
            "invalid_request", notification.id, f"action is {notification.action_state}"
        )
    return notification


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
        raise MobileGateActionError(
            "invalid_request", "questions", "question_request.json missing questions"
        )
    index = question_index or 0
    try:
        question = questions[index]
    except IndexError as exc:
        raise MobileGateActionError(
            "invalid_request", "question_index", "question index is not available"
        ) from exc
    if not isinstance(question, dict):
        raise MobileGateActionError(
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
            raise MobileGateActionError(
                "invalid_request", "custom_answer", "custom answer is required"
            )
        selected = []
        custom_feedback = custom_answer
    else:
        raise MobileGateActionError(
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
        raise MobileGateActionError(
            "invalid_request", "options", "question is missing options"
        )
    option: Any
    if selected_option_id is not None:
        for option in options:
            if isinstance(option, dict) and option.get("id") == selected_option_id:
                label = option.get("label")
                if isinstance(label, str):
                    return label
        raise MobileGateActionError(
            "invalid_request",
            "selected_option_id",
            "question option id is not available",
        )
    if selected_option_index is None:
        raise MobileGateActionError(
            "invalid_request",
            "selected_option",
            "question answer requires a selected option",
        )
    try:
        option = options[selected_option_index]
    except IndexError as exc:
        raise MobileGateActionError(
            "invalid_request",
            "selected_option_index",
            "question option index is not available",
        ) from exc
    if isinstance(option, dict) and isinstance(option.get("label"), str):
        return option["label"]
    raise MobileGateActionError(
        "invalid_request", "label", "question option is missing a label"
    )
