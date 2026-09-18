"""Notifications for durable gate execution failures."""

from __future__ import annotations

import logging
import shlex
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sase.core.time import get_timezone
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.journal import (
    ExecutionFailureFacts,
    incomplete_attempt,
    read_journal_records,
)
from sase.notifications.models import Notification, normalize_notification_tags

log = logging.getLogger(__name__)

GATE_EXECUTION_FAILED_ACTION = "GateExecutionFailed"
_SENDER = "gate"
_PRE_RESPONSE_STAGES = frozenset({"command", "terminal_prepare"})
_NOTIFICATION_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://sase.dev/notifications/gate-execution-failed"
)


def publish_gate_execution_failed(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    failure: ExecutionFailureFacts,
    *,
    source: str,
) -> None:
    """Publish one deduped recovery notification for *failure*.

    The later ACE phase owns the rich retry modal. This phase publishes the
    durable action row and enough action data for every surface to degrade
    explicitly instead of losing the failure.
    """
    original_notification_id = envelope.get("notification_id")
    if not isinstance(original_notification_id, str) or not original_notification_id:
        return

    request_id = str(envelope.get("request_id") or "")
    request_kind = str(envelope.get("kind") or "")
    action_data = gate_failure_action_data(bundle_path, envelope, failure)
    recovery_actions = _recovery_actions(failure.stage)
    notes = [
        f"Gate execution failed: {request_kind}/{request_id}",
        f"{failure.stage}: {failure.message or failure.code}",
        f"Recovery: {', '.join(recovery_actions)}",
    ]
    error_path = bundle_path / failure.error_record if failure.error_record else None
    files = [str(error_path)] if error_path is not None and error_path.exists() else []
    row = Notification(
        id=_gate_execution_failed_notification_id(
            request_kind=request_kind,
            request_id=request_id,
            acceptance_id=failure.acceptance_id,
            attempt_id=failure.attempt_id,
            outcome_id=failure.outcome_id,
        ),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=_SENDER,
        icon="!",
        notes=notes,
        files=files,
        action=GATE_EXECUTION_FAILED_ACTION,
        action_data=action_data,
        tags=normalize_notification_tags(["gate", "execution", "error"]),
        dedup_key=_dedup_key(request_kind, request_id, failure),
    )

    try:
        from sase.notifications.store import upsert_notification

        upsert_notification(
            row,
            plus_one_note=f"{failure.stage}: {failure.code}",
            plus_one_timestamp=row.timestamp,
        )
    except Exception:
        log.warning(
            "Failed to publish gate execution failure notification", exc_info=True
        )


def dismiss_gate_execution_failed(
    *,
    bundle_path: Path | None = None,
    envelope: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    request_kind: str | None = None,
) -> None:
    """Dismiss all open failure notifications matching one gate."""
    if envelope is not None:
        request_id = str(envelope.get("request_id") or request_id or "")
        request_kind = str(envelope.get("kind") or request_kind or "")
    bundle_text = str(bundle_path) if bundle_path is not None else ""
    ids: list[str] = []
    try:
        from sase.notifications.store import load_notifications, mark_many_dismissed

        for notification in load_notifications(include_dismissed=False):
            if notification.action != GATE_EXECUTION_FAILED_ACTION:
                continue
            data = notification.action_data
            if request_id and data.get("request_id") != request_id:
                continue
            if request_kind and data.get("request_kind") != request_kind:
                continue
            if bundle_text and data.get("bundle_path") != bundle_text:
                continue
            ids.append(notification.id)
        mark_many_dismissed(ids)
    except Exception:
        log.warning(
            "Failed to dismiss gate execution failure notifications", exc_info=True
        )


def _recovery_actions(stage: str) -> tuple[str, ...]:
    if stage in _PRE_RESPONSE_STAGES:
        return ("resume", "restart", "cancel")
    return ("resume",)


def gate_failure_action_data(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    failure: ExecutionFailureFacts | Mapping[str, Any],
) -> dict[str, str]:
    """Return the stable action payload for one current gate execution failure."""
    request_id = str(envelope.get("request_id") or "")
    request_kind = str(envelope.get("kind") or "")
    acceptance_id = _failure_value(failure, "acceptance_id")
    attempt_id = _failure_value(failure, "attempt_id")
    outcome_id = _failure_value(failure, "outcome_id")
    stage = _failure_value(failure, "stage")
    code = _failure_value(failure, "code")
    message = _failure_value(failure, "message")
    error_record = _failure_value(failure, "error_record")
    error_path = str(bundle_path / error_record) if error_record else ""
    selected_ids = _selected_option_ids(bundle_path, failure)
    action_data = {
        "request_id": request_id,
        "request_kind": request_kind,
        "gate_ref": f"{request_kind}/{request_id}"
        if request_kind and request_id
        else "",
        "gate_shell_ref": request_id if isinstance(envelope.get("shell"), dict) else "",
        "bundle_path": str(bundle_path),
        "gate_notification_id": str(envelope.get("notification_id") or ""),
        # Compatibility with the first failure-notification rollout.
        "failed_notification_id": str(envelope.get("notification_id") or ""),
        "acceptance_id": acceptance_id,
        "attempt_id": attempt_id,
        "outcome_id": outcome_id,
        "stage": stage,
        "code": code,
        "message": message,
        "error_record": error_record,
        "error_report_path": error_path,
        "recovery_actions": ",".join(_recovery_actions(stage)),
    }
    resume = _gate_answer_command(request_kind, request_id, selected_ids, "resume")
    restart = _gate_answer_command(request_kind, request_id, selected_ids, "restart")
    cancel = _gate_cancel_command(request_kind, request_id)
    if resume:
        action_data["resume_command"] = resume
    if restart and "restart" in _recovery_actions(stage):
        action_data["restart_command"] = restart
    if cancel and "cancel" in _recovery_actions(stage):
        action_data["cancel_command"] = cancel
    return action_data


def gate_failure_requester_message(
    prefix: str,
    failure: Mapping[str, Any] | None,
    recovery: Mapping[str, str] | None = None,
) -> str:
    """Render one actionable failure summary for waiters and requesters."""
    parts = [prefix]
    if isinstance(failure, Mapping):
        stage = failure.get("stage")
        code = failure.get("code")
        message = failure.get("message")
        if stage or code:
            parts.append(f"{stage or 'execution'}: {code or 'failed'}")
        if isinstance(message, str) and message:
            parts.append(message)
    if recovery:
        error_report = recovery.get("error_report_path")
        if error_report:
            parts.append(f"error report: {error_report}")
        for label, key in (
            ("resume", "resume_command"),
            ("restart", "restart_command"),
            ("cancel", "cancel_command"),
        ):
            command = recovery.get(key)
            if command:
                parts.append(f"{label}: {command}")
    return "\n".join(parts)


def _gate_execution_failed_notification_id(
    *,
    request_kind: str,
    request_id: str,
    acceptance_id: str | None,
    attempt_id: str,
    outcome_id: str,
) -> str:
    """Return the deterministic row id for one gate/acceptance failure."""
    identity = acceptance_id or f"legacy:{attempt_id or outcome_id}"
    return str(
        uuid5(_NOTIFICATION_NAMESPACE, f"{request_kind}\0{request_id}\0{identity}")
    )


def _dedup_key(
    request_kind: str, request_id: str, failure: ExecutionFailureFacts
) -> str:
    acceptance_id = (
        failure.acceptance_id or f"legacy:{failure.attempt_id or failure.outcome_id}"
    )
    return f"gate-execution-failed:{request_kind}:{request_id}:{acceptance_id}"


def _selected_option_ids(
    bundle_path: Path,
    failure: ExecutionFailureFacts | Mapping[str, Any],
) -> tuple[str, ...]:
    response_path = bundle_path / "response.json"
    response_selected = _response_selected_option_ids(response_path)
    if response_selected:
        return response_selected
    attempt_id = _failure_value(failure, "attempt_id")
    pending = incomplete_attempt(bundle_path, response_exists=response_path.exists())
    if pending is not None and pending.attempt_id == attempt_id:
        return tuple(pending.selected_option_ids)
    acceptance_id = _failure_value(failure, "acceptance_id")
    receipt_selected = _receipt_selected_option_ids(bundle_path, acceptance_id)
    if receipt_selected:
        return receipt_selected
    for record in reversed(read_journal_records(bundle_path)):
        if record.get("event") != "attempt_started":
            continue
        if attempt_id and record.get("attempt_id") != attempt_id:
            continue
        if acceptance_id and record.get("acceptance_id") != acceptance_id:
            continue
        raw = record.get("selected_option_ids")
        if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
            return tuple(raw)
    return ()


def _receipt_selected_option_ids(
    bundle_path: Path, acceptance_id: str
) -> tuple[str, ...]:
    if not acceptance_id:
        return ()
    try:
        receipt = read_json_object(bundle_path / "decision_receipt.json")
    except Exception:
        return ()
    if receipt.get("acceptance_id") != acceptance_id:
        return ()
    raw = receipt.get("selected_option_ids")
    if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
        return tuple(raw)
    return ()


def _response_selected_option_ids(response_path: Path) -> tuple[str, ...]:
    try:
        response = read_json_object(response_path)
    except Exception:
        return ()
    raw = response.get("selected_option_ids")
    if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
        return tuple(raw)
    return ()


def _gate_answer_command(
    request_kind: str,
    request_id: str,
    selected_option_ids: tuple[str, ...],
    retry: str,
) -> str:
    if not request_kind or not request_id or not selected_option_ids:
        return ""
    argv = ["sase", "gate", "answer", "--kind", request_kind, "--id", request_id]
    for option_id in selected_option_ids:
        argv.extend(["--option", option_id])
    argv.append(f"--{retry}")
    return shlex.join(argv)


def _gate_cancel_command(request_kind: str, request_id: str) -> str:
    if not request_kind or not request_id:
        return ""
    return shlex.join(
        ["sase", "gate", "cancel", "--kind", request_kind, "--id", request_id]
    )


def _failure_value(
    failure: ExecutionFailureFacts | Mapping[str, Any],
    key: str,
) -> str:
    if isinstance(failure, ExecutionFailureFacts):
        value = getattr(failure, key)
    else:
        value = failure.get(key)
    return value if isinstance(value, str) else ""


__all__ = [
    "GATE_EXECUTION_FAILED_ACTION",
    "dismiss_gate_execution_failed",
    "gate_failure_action_data",
    "gate_failure_requester_message",
    "publish_gate_execution_failed",
]
