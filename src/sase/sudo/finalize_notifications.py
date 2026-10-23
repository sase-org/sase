"""Notifications for detached sudo finalize failures."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sase.core.time import get_timezone
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import RESPONSE_FILENAME
from sase.notifications.models import Notification, normalize_notification_tags
from sase.procs.logs import proc_log_path
from sase.sudo.execution_state import SudoExecutionState

log = logging.getLogger(__name__)

VIEW_ERROR_REPORT_ACTION = "ViewErrorReport"
_SENDER = "sudo"
_NOTIFICATION_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://sase.dev/notifications/sudo-finalize-failed"
)


def publish_sudo_finalize_failed(
    bundle_root: Path,
    exc: GateError,
    *,
    state: SudoExecutionState | None,
    receipt: Mapping[str, Any] | None,
    error_record: str | None,
) -> None:
    """Publish one deduped finalize-failure notification. Best-effort."""
    request_id = state.gate_id if state is not None else bundle_root.name
    lane = _lane(state)
    error_path = _error_report_path(bundle_root, state=state, error_record=error_record)
    if (bundle_root / RESPONSE_FILENAME).exists():
        recovery_note = (
            "Recovery: the answer is recorded; do not rerun the commands. Resume the "
            f"answered shell handoff with `sase gate answer --kind sudo --id "
            f"{request_id} --option approve --resume`."
        )
    else:
        recovery_note = (
            f"Recovery: sase sudo answer {request_id} --run reruns the selected "
            "commands, --command <id> selects a subset, and --deny denies."
        )
    notes = [
        f"Sudo finalize failed: sudo/{request_id} ({lane})",
        f"{exc.code}: {exc}",
        _commands_ran_note(receipt),
        recovery_note,
    ]
    files = [str(error_path)] if error_path is not None and error_path.exists() else []
    action_data = {
        "request_id": request_id,
        "request_kind": "sudo",
        "bundle_path": str(bundle_root),
    }
    if error_path is not None:
        action_data["error_report_path"] = str(error_path)
    row = Notification(
        id=_notification_id(request_id),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=_SENDER,
        icon="!",
        notes=notes,
        files=files,
        action=VIEW_ERROR_REPORT_ACTION,
        action_data=action_data,
        tags=normalize_notification_tags(["sudo", "gate", "error"]),
        dedup_key=_dedup_key(request_id),
    )
    try:
        from sase.notifications.store import upsert_notification

        upsert_notification(
            row,
            plus_one_note=f"{exc.code}: {exc}",
            plus_one_timestamp=row.timestamp,
        )
    except Exception:
        log.warning(
            "Failed to publish sudo finalize failure notification", exc_info=True
        )


def dismiss_sudo_finalize_failed(
    *,
    request_id: str | None = None,
    bundle_path: Path | None = None,
) -> None:
    """Dismiss open sudo finalize-failure notifications for one gate."""
    bundle_text = str(bundle_path) if bundle_path is not None else ""
    ids: list[str] = []
    try:
        from sase.notifications.store import load_notifications, mark_many_dismissed

        for notification in load_notifications(include_dismissed=False):
            if notification.action != VIEW_ERROR_REPORT_ACTION:
                continue
            data = notification.action_data
            if data.get("request_kind") != "sudo":
                continue
            if request_id and data.get("request_id") != request_id:
                continue
            if bundle_text and data.get("bundle_path") != bundle_text:
                continue
            ids.append(notification.id)
        mark_many_dismissed(ids)
    except Exception:
        log.warning(
            "Failed to dismiss sudo finalize failure notifications", exc_info=True
        )


def _notification_id(request_id: str) -> str:
    return str(uuid5(_NOTIFICATION_NAMESPACE, request_id))


def _dedup_key(request_id: str) -> str:
    return f"sudo-finalize-failed:{request_id}"


def _lane(state: SudoExecutionState | None) -> str:
    if state is None:
        return "unknown"
    if state.target_kind == "remote":
        host = state.target_host or "remote"
        return f"remote/{host}"
    return "local"


def _error_report_path(
    bundle_root: Path,
    *,
    state: SudoExecutionState | None,
    error_record: str | None,
) -> Path | None:
    if state is not None and state.finalize_proc_id:
        try:
            return proc_log_path(state.finalize_proc_id)
        except Exception:
            log.warning("Failed to resolve sudo finalize proc log path", exc_info=True)
    if error_record:
        return bundle_root / error_record
    return None


def _commands_ran_note(receipt: Mapping[str, Any] | None) -> str:
    if receipt is None:
        return "no ledger; commands may have partially run"
    entries = receipt.get("entries")
    if not isinstance(entries, list):
        outcome = str(receipt.get("outcome") or "unknown")
        return f"no ledger entries; commands may have partially run (ledger outcome {outcome})"
    total = len(entries)
    ran = 0
    exit_zero = 0
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") == "ran":
            ran += 1
            if item.get("exit_code") == 0:
                exit_zero += 1
    outcome = str(receipt.get("outcome") or "unknown")
    if ran == total and total > 0 and exit_zero == ran:
        return f"commands ran: {ran}/{total} exit 0 (ledger outcome {outcome})"
    return f"commands ran: {ran}/{total} (ledger outcome {outcome})"


__all__ = ["dismiss_sudo_finalize_failed", "publish_sudo_finalize_failed"]
