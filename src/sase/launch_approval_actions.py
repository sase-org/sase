"""Shared LaunchApproval response protocol and side effects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sase.agent.launch_preview import LAUNCH_REQUEST_FILE, LAUNCH_RESPONSE_FILE


@dataclass(frozen=True)
class _LaunchApprovalActionContext:
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
    notification: _LaunchApprovalActionContext,
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
    notification: _LaunchApprovalActionContext,
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
    notification: _LaunchApprovalActionContext,
    bundle_path: Path,
    choice: str,
    *,
    feedback: str | None,
) -> LaunchApprovalActionResult:
    """Execute one registered launch option through the common gate executor."""
    from sase.gate_shell.log import bind_gate_shell_execution_callbacks
    from sase.gate_shell.settlement import settle_gate_shell
    from sase.gate_shell.store import find_gate_shell_by_gate_id
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import RESPONSE_FILENAME

    # Rejecting with a note no longer selects a different option: `feedback`
    # is a declared input on `reject`, and the executor injects the note into
    # every selected option whose schema declares it.
    option_id = choice
    envelope, _adapter = load_and_verify_bundle(bundle_path)
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
        execution = execute_gate_selection(
            bundle_path,
            [option_id],
            feedback=feedback,
            source="launch_response",
            **execution_kwargs,
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise LaunchApprovalActionError(code, exc.target, str(exc)) from exc
    if gate_shell is not None:
        settle_gate_shell(
            gate_shell,
            gate_state="answered",
            reason="launch approval answered",
        )
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
        summary = command_result.get("admission_summary")
        if isinstance(summary, dict):
            message = _admission_message(summary, launched_count)
        else:
            message = (
                f"Launch approved and dispatched {launched_count} agent"
                f"{'s' if launched_count != 1 else ''}"
            )
    elif option_id == "reject":
        message = "Feedback received" if feedback else "Launch rejected"
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
    notification: _LaunchApprovalActionContext,
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
) -> _LaunchApprovalActionContext:
    """Build a host-side action context from a notification-like object."""
    return _LaunchApprovalActionContext(
        id=str(notification.id),
        host_files=tuple(str(Path(path).expanduser()) for path in notification.files),
        host_action_data={
            str(key): str(value) for key, value in notification.action_data.items()
        },
    )


def _admission_message(summary: dict[str, Any], launched_count: int) -> str:
    total = int(summary.get("total") or 0)
    skipped = int(summary.get("skipped") or 0)
    condition_errors = int(summary.get("condition_errors") or 0)
    launch_errors = int(summary.get("launch_errors") or 0)
    return (
        f"Launch admitted: {launched_count} launched, {skipped} skipped, "
        f"{condition_errors} condition error(s), {launch_errors} launch error(s)"
        f" (total {total})"
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
        return response, "Feedback received" if feedback else "Launch rejected"
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
    "LaunchApprovalActionError",
    "LaunchApprovalActionResult",
    "execute_launch_approval_response",
    "launch_context_from_notification",
]
