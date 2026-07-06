"""Shared LaunchApproval response protocol and side effects."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from sase.agent.launch_preview import LAUNCH_REQUEST_FILE, LAUNCH_RESPONSE_FILE

LaunchApprovalChoice = Literal["approve", "reject", "feedback"]


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
    """Write the response for a resolved LaunchApproval notification."""
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
    run_launch_side_effects(notification, choice)
    return LaunchApprovalActionResult(
        notification_id=notification.id,
        response_file=LAUNCH_RESPONSE_FILE,
        response_path=response_path,
        response_json=response_json,
        message=message,
    )


def get_auto_launch_approval_action() -> LaunchApprovalChoice | None:
    """Return the launch-specific auto-approval action, if one is active."""
    for env_name in (
        "SASE_AGENT_AUTO_APPROVE_LAUNCH_ACTION",
        "SASE_AGENT_AUTO_LAUNCH_ACTION",
    ):
        action = _normalize_launch_action(os.environ.get(env_name))
        if action is not None:
            return action

    meta = _read_agent_meta()
    action = _normalize_launch_action(meta.get("auto_approve_launch_action"))
    if action is not None:
        return action

    if os.environ.get("SASE_AGENT_AUTO_APPROVE_LAUNCH") or meta.get("approve_launch"):
        return "approve"
    if os.environ.get("SASE_AGENT_AUTO_APPROVE") or meta.get("approve"):
        return "approve"

    return None


def run_launch_side_effects(
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


def _normalize_launch_action(value: object) -> LaunchApprovalChoice | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"approve", "reject", "feedback"}:
        return normalized  # type: ignore[return-value]
    return None


def _read_agent_meta() -> dict[str, object]:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return {}
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "LaunchApprovalActionContext",
    "LaunchApprovalActionError",
    "LaunchApprovalActionResult",
    "execute_launch_approval_response",
    "get_auto_launch_approval_action",
    "launch_context_from_notification",
    "run_launch_side_effects",
]
