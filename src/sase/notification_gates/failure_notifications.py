"""Notifications for durable gate execution failures."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.notification_gates.journal import ExecutionFailureFacts
from sase.notifications.models import Notification, normalize_notification_tags

log = logging.getLogger(__name__)

GATE_EXECUTION_FAILED_ACTION = "GateExecutionFailed"
_SENDER = "gate"
_PRE_RESPONSE_STAGES = frozenset({"command", "terminal_prepare"})


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
    notification_id = envelope.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        return

    request_id = str(envelope.get("request_id") or "")
    request_kind = str(envelope.get("kind") or "")
    recovery_actions = _recovery_actions(failure.stage)
    action_data = {
        "request_id": request_id,
        "request_kind": request_kind,
        "bundle_path": str(bundle_path),
        "failed_notification_id": notification_id,
        "acceptance_id": failure.acceptance_id or "",
        "attempt_id": failure.attempt_id,
        "outcome_id": failure.outcome_id,
        "stage": failure.stage,
        "code": failure.code,
        "error_record": failure.error_record,
        "recovery_actions": ",".join(recovery_actions),
    }
    notes = [
        f"Gate execution failed: {request_kind}/{request_id}",
        f"{failure.stage}: {failure.message or failure.code}",
        f"Recovery: {', '.join(recovery_actions)}",
    ]
    error_path = bundle_path / failure.error_record if failure.error_record else None
    files = [str(error_path)] if error_path is not None and error_path.exists() else []
    row = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=_SENDER,
        icon="!",
        notes=notes,
        files=files,
        action=GATE_EXECUTION_FAILED_ACTION,
        action_data=action_data,
        tags=normalize_notification_tags(["gate", "failure", request_kind]),
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


def _dedup_key(
    request_kind: str, request_id: str, failure: ExecutionFailureFacts
) -> str:
    acceptance_id = failure.acceptance_id or "legacy"
    return (
        "gate-execution-failed:"
        f"{request_kind}:{request_id}:{acceptance_id}:{failure.outcome_id}"
    )


__all__ = [
    "GATE_EXECUTION_FAILED_ACTION",
    "dismiss_gate_execution_failed",
    "publish_gate_execution_failed",
]
