"""Daemon-backed notification write adapters with direct source-store fallback."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.write_facade import DaemonWriteResult, write_or_fallback
from sase.notifications.models import Notification

NOTIFICATION_WRITE_CAPABILITY = "notifications.write"


def append_notification(
    notification: Notification,
    *,
    direct_writer: Callable[[], None],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[None]:
    payload = {"notification": _notification_dict(notification)}
    return write_or_fallback(
        "notifications.append",
        args=args,
        client=client,
        required_capability=NOTIFICATION_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "notifications.append",
            payload,
            idempotency_key=_idempotency_key("notifications.append", payload),
        ),
        direct_writer=direct_writer,
    )


def apply_notification_state_update(
    update: dict[str, Any],
    *,
    direct_writer: Callable[[], Any],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[Any]:
    payload = {"update": update}
    return write_or_fallback(
        "notifications.state_update",
        args=args,
        client=client,
        required_capability=NOTIFICATION_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _outcome_from_write(
            daemon.write(
                "notifications.state_update",
                _write_data(
                    payload,
                    idempotency_key=_idempotency_key(
                        "notifications.state_update", payload
                    ),
                ),
            )
        ),
        direct_writer=direct_writer,
    )


def register_pending_action(
    action: dict[str, Any],
    *,
    direct_writer: Callable[[], None],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[None]:
    payload = {"action": action}
    return write_or_fallback(
        "pending_actions.register",
        args=args,
        client=client,
        required_capability=NOTIFICATION_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "pending_actions.register",
            payload,
            idempotency_key=_idempotency_key("pending_actions.register", payload),
        ),
        direct_writer=direct_writer,
    )


def _write_void(
    daemon: LocalDaemonClient,
    surface: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
) -> None:
    daemon.write(surface, _write_data(payload, idempotency_key=idempotency_key))


def _write_data(payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "home",
        "idempotency_key": idempotency_key,
        "actor": {
            "schema_version": 1,
            "actor_type": "cli",
            "name": "sase-python",
        },
        "payload": payload,
    }


def _outcome_from_write(response: dict[str, Any]) -> Any:
    snapshot = response.get("outcome", {}).get("projection_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("outcome"), dict):
        return SimpleNamespace(
            schema_version=1,
            matched_count=0,
            changed_count=0,
            appended_count=0,
            rewritten=False,
            notifications=[],
            counts={},
            expired_ids=[],
            stats={},
        )
    outcome = dict(snapshot["outcome"])
    outcome["notifications"] = [
        Notification(**item)
        for item in outcome.get("notifications", [])
        if isinstance(item, dict)
    ]
    return SimpleNamespace(**outcome)


def _notification_dict(notification: Notification) -> dict[str, Any]:
    return dataclasses.asdict(notification)


def _idempotency_key(surface: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{surface}:{digest}"


__all__ = [
    "NOTIFICATION_WRITE_CAPABILITY",
    "append_notification",
    "apply_notification_state_update",
    "register_pending_action",
]
