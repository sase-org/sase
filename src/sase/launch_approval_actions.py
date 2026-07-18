"""Shared LaunchApproval response protocol and side effects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sase.agent.launch_preview import LAUNCH_REQUEST_FILE, LAUNCH_RESPONSE_FILE


@dataclass(frozen=True)
class LaunchApprovalActionContext:
    id: str
    host_files: tuple[str, ...]
    host_action_data: dict[str, str]


@dataclass(frozen=True)
class LaunchApprovalActionResult:
    notification_id: str
    response_file: str
    response_path: Path
    response_json: dict[str, Any]
    message: str
    launched_count: int = 0


class _NotificationLike(Protocol):
    id: str
    files: list[str]
    action_data: dict[str, str]


class LaunchApprovalActionError(RuntimeError):
    """Deterministic host-side launch action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def execute_launch_approval_response(
    notification: LaunchApprovalActionContext,
    choice: str,
    *,
    feedback: str | None = None,
) -> LaunchApprovalActionResult:
    """Resolve a neutral LaunchApproval, with legacy in-flight fallback."""
    from sase.notification_gates.paths import resolve_action_bundle

    bundle = resolve_action_bundle("LaunchApproval", notification.host_action_data)
    if bundle is not None and not bundle.legacy:
        return _execute_neutral_launch_approval_response(
            notification,
            bundle.root,
            choice,
            feedback=feedback,
        )
    return _execute_legacy_launch_approval_response(
        notification,
        choice,
        feedback=feedback,
    )


def _execute_legacy_launch_approval_response(
    notification: LaunchApprovalActionContext,
    choice: str,
    *,
    feedback: str | None,
) -> LaunchApprovalActionResult:
    """Resolve an in-flight launch request from the legacy layout."""
    raw_response_dir = notification.host_action_data.get("response_dir")
    if not raw_response_dir:
        raise LaunchApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )

    response_dir = Path(raw_response_dir).expanduser()
    if not response_dir.is_dir():
        raise LaunchApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    if not (response_dir / LAUNCH_REQUEST_FILE).is_file():
        raise LaunchApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "launch request was already consumed",
        )

    response_json, message = _launch_response_json(choice, feedback=feedback)
    response_path = response_dir / LAUNCH_RESPONSE_FILE
    _write_json_once(response_path, response_json, notification.id)
    launched_count = 0
    if choice == "approve":
        try:
            from sase.agent.launch_request import dispatch_approved_launch_request

            dispatch_result = dispatch_approved_launch_request(response_dir)
        except Exception as exc:
            response_json["dispatch_status"] = "failed"
            response_json["dispatch_error"] = str(exc)
            _write_json_replace(response_path, response_json)
            raise LaunchApprovalActionError(
                "dispatch_failed", notification.id, str(exc)
            ) from exc
        launched_count = dispatch_result.launched_count
        response_json["dispatch_status"] = "launched"
        response_json["launched_count"] = launched_count
        _write_json_replace(response_path, response_json)
        message = (
            f"Launch approved and dispatched {launched_count} agent"
            f"{'s' if launched_count != 1 else ''}"
        )
    _run_launch_side_effects(notification, choice)
    return LaunchApprovalActionResult(
        notification_id=notification.id,
        response_file=LAUNCH_RESPONSE_FILE,
        response_path=response_path,
        response_json=response_json,
        message=message,
        launched_count=launched_count,
    )


def _execute_neutral_launch_approval_response(
    notification: LaunchApprovalActionContext,
    bundle_path: Path,
    choice: str,
    *,
    feedback: str | None,
) -> LaunchApprovalActionResult:
    """Execute one registered launch option through the common gate executor."""
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import RESPONSE_FILENAME

    option_id = "feedback" if choice == "reject" and feedback else choice
    input_data: dict[str, Any] = {}
    if option_id == "feedback":
        if not feedback:
            raise LaunchApprovalActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        input_data["feedback"] = feedback
    try:
        execution = execute_gate_selection(
            bundle_path,
            [option_id],
            input_data,
            feedback=feedback,
            source="launch_response",
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise LaunchApprovalActionError(code, exc.target, str(exc)) from exc
    if execution.already_completed:
        raise LaunchApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "response already exists",
        )

    response_json = execution.response
    option_results = response_json.get("option_results")
    command_result = (
        next(
            (
                entry.get("result")
                for entry in option_results
                if isinstance(entry, dict) and entry.get("id") == option_id
            ),
            None,
        )
        if isinstance(option_results, list)
        else None
    )
    if not isinstance(command_result, dict):
        raise LaunchApprovalActionError(
            "invalid_response",
            notification.id,
            "launch command returned no result object",
        )
    launched_count = 0
    if option_id == "approve":
        if command_result.get("dispatch_status") == "failed":
            raise LaunchApprovalActionError(
                "dispatch_failed",
                notification.id,
                str(command_result.get("dispatch_error") or "launch dispatch failed"),
            )
        launched_count = int(command_result.get("launched_count") or 0)
        message = (
            f"Launch approved and dispatched {launched_count} agent"
            f"{'s' if launched_count != 1 else ''}"
        )
    elif option_id == "reject":
        message = "Launch rejected"
    elif option_id == "feedback":
        message = "Feedback received"
    else:  # The registered executor normally rejects this first.
        raise LaunchApprovalActionError(
            "unsupported_action", option_id, "unsupported launch action option"
        )

    _run_launch_side_effects(notification, option_id)
    return LaunchApprovalActionResult(
        notification_id=notification.id,
        response_file=RESPONSE_FILENAME,
        response_path=bundle_path / RESPONSE_FILENAME,
        response_json=response_json,
        message=message,
        launched_count=launched_count,
    )


def _run_launch_side_effects(
    notification: LaunchApprovalActionContext,
    choice: str,
) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification.id)
    except Exception:
        pass

    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(notification.id, source="launch_response", action=choice)
    except Exception:
        pass


def launch_context_from_notification(
    notification: _NotificationLike,
) -> LaunchApprovalActionContext:
    """Build a host-side action context from a notification-like object."""
    return LaunchApprovalActionContext(
        id=str(notification.id),
        host_files=tuple(str(Path(path).expanduser()) for path in notification.files),
        host_action_data={
            str(key): str(value) for key, value in notification.action_data.items()
        },
    )


def _launch_response_json(
    choice: str,
    *,
    feedback: str | None,
) -> tuple[dict[str, Any], str]:
    if choice == "approve":
        return {"action": "approve"}, "Launch approved"
    if choice == "reject":
        response: dict[str, Any] = {"action": "reject"}
        if feedback is not None:
            response["feedback"] = feedback
        return response, "Launch rejected"
    if choice == "feedback":
        if not feedback:
            raise LaunchApprovalActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return {"action": "reject", "feedback": feedback}, "Feedback received"
    raise LaunchApprovalActionError(
        "unsupported_action", choice, "unsupported launch action choice"
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
        raise LaunchApprovalActionError(
            "conflict_already_handled", notification_id, "response already exists"
        ) from exc


def _write_json_replace(response_path: Path, response_json: dict[str, Any]) -> None:
    with response_path.open("w", encoding="utf-8") as f:
        json.dump(response_json, f, indent=2)
        f.write("\n")


__all__ = [
    "LaunchApprovalActionContext",
    "LaunchApprovalActionError",
    "LaunchApprovalActionResult",
    "execute_launch_approval_response",
    "launch_context_from_notification",
]
