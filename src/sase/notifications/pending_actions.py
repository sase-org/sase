"""Shared host pending-action storage for notification transports."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.core.rust import require_rust_binding
from sase.notification_gates.registry import adapter_for_kind, registered_gate_kinds
from sase.notifications.models import Notification

PENDING_ACTIONS_PATH: Path | None = None
LEGACY_TELEGRAM_PENDING_ACTIONS_PATH: Path | None = None
PENDING_ACTION_PREFIX_LEN = 8
STALE_THRESHOLD_SECONDS = 24 * 60 * 60

_ACTION_KIND_BY_NOTIFICATION_ACTION = {
    adapter.action: adapter.pending_action_kind
    for adapter in (adapter_for_kind(kind) for kind in registered_gate_kinds())
}


@dataclass(frozen=True)
class _PrefixResolution:
    notification_id: str
    prefix: str
    prefix_len: int
    resolution: str


def _pending_actions_path() -> Path:
    return PENDING_ACTIONS_PATH or sase_subdir("pending_actions") / "actions.json"


def _legacy_telegram_pending_actions_path() -> Path:
    return (
        LEGACY_TELEGRAM_PENDING_ACTIONS_PATH
        or sase_subdir("telegram") / "pending_actions.json"
    )


def register_notification(
    notification: Notification, *, now: float | None = None
) -> None:
    """Register an actionable notification in the shared pending-action store."""
    entry = _entry_from_notification(
        notification, now=time.time() if now is None else now
    )
    if entry is None:
        return
    require_rust_binding("register_pending_action")(str(_pending_actions_path()), entry)


def action_state_for_notification(
    notification: Notification,
    *,
    now: float | None = None,
    store: Mapping[str, Any] | None = None,
) -> str:
    """Return the mobile action state for a notification without mutating it."""
    current = time.time() if now is None else now
    loaded_store = store if store is not None else _load_store(include_legacy=True)
    pending = next(
        (
            entry
            for entry in loaded_store.get("actions", {}).values()
            if isinstance(entry, dict)
            and entry.get("notification_id") == notification.id
        ),
        None,
    )
    return _state_for_notification(notification, pending, current)


def resolve_prefix(prefix: str, *, include_legacy: bool = True) -> _PrefixResolution:
    """Resolve a full notification id or unique notification-id prefix."""
    store = _load_store(include_legacy=include_legacy)
    ids = [
        str(entry.get("notification_id"))
        for entry in store.get("actions", {}).values()
        if isinstance(entry, dict)
        and entry.get("notification_id")
        and entry.get("action") in _ACTION_KIND_BY_NOTIFICATION_ACTION
    ]
    exact = [notification_id for notification_id in ids if notification_id == prefix]
    if len(exact) == 1:
        return _PrefixResolution(prefix, prefix, len(prefix), "exact")
    if len(exact) > 1:
        return _PrefixResolution(prefix, prefix, len(prefix), "duplicate_full_id")
    matches = [
        notification_id for notification_id in ids if notification_id.startswith(prefix)
    ]
    if len(matches) == 1:
        return _PrefixResolution(matches[0], prefix, len(prefix), "unique_prefix")
    if not matches:
        return _PrefixResolution("", prefix, len(prefix), "missing")
    return _PrefixResolution("", prefix, len(prefix), "ambiguous_prefix")


def read_pending_action_store(*, include_legacy: bool = False) -> dict[str, Any]:
    """Return the current pending-action store."""
    return _load_store(include_legacy=include_legacy)


# symvision: https://github.com/sase-org/sase-telegram.git
def merge_transport_record(
    notification_id: str,
    transport: str,
    record: Mapping[str, Any],
    *,
    now: float | None = None,
) -> bool:
    """Merge a transport-owned record into an existing action entry.

    The entry is located by full notification id or unique notification-id
    prefix. ``record`` should hold only transport-owned data such as
    ``chat_id`` and ``message_id``. New fields are merged into an existing
    record for ``transport``; otherwise the record is appended. Returns ``True``
    when an entry
    was updated, ``False`` when no matching action exists.
    """
    return bool(
        require_rust_binding("merge_pending_action_transport")(
            str(_pending_actions_path()), notification_id, transport, dict(record), now
        )
    )


def mark_already_handled(
    notification_id: str,
    *,
    source: str,
    action: str | None = None,
    now: float | None = None,
) -> bool:
    """Mark an action entry ``already_handled`` with audit metadata.

    Locates the entry by full notification id or unique prefix and records why
    it was resolved (``source``, timestamp, and the optional response
    ``action``). Returns ``True`` when an entry was updated.
    """
    return bool(
        require_rust_binding("mark_pending_action_handled")(
            str(_pending_actions_path()), notification_id, source, action, now
        )
    )


def unregister_notification(notification_id: str) -> bool:
    """Remove a gate action during creation compensation."""
    return bool(
        require_rust_binding("remove_pending_action")(
            str(_pending_actions_path()), notification_id
        )
    )


def mark_plan_approval_auto_handled(
    *,
    plan_file: str,
    agent_timestamp: str | None = None,
    agent_root_timestamp: str | None = None,
    agent_name: str | None = None,
    source: str = "auto_approve",
    action: str | None = None,
    now: float | None = None,
) -> list[str]:
    """Mark PlanApproval actions for ``plan_file`` + agent identity handled.

    Scans both shared and legacy-merged entries for PlanApproval actions whose
    plan file matches ``plan_file`` and whose action data matches at least one
    provided agent identity field (``agent_timestamp``, ``agent_root_timestamp``
    or ``agent_name``). Matching legacy-only records are promoted into the
    shared store so transport cleanup can see the handled state. Returns the
    notification ids that were marked.

    Matching never falls back to plan file alone: with no identity field
    provided nothing is marked, avoiding clobbering unrelated approvals when a
    plan path is reused.
    """
    return list(
        _transport_operation(
            "mark_plan_handled",
            now=now,
            include_legacy=True,
            plan_file=plan_file,
            identity={
                key: value
                for key, value in {
                    "agent_timestamp": agent_timestamp,
                    "agent_root_timestamp": agent_root_timestamp,
                    "agent_name": agent_name,
                }.items()
                if value
            },
            source=source,
            action=action,
        )
    )


def _load_store(*, include_legacy: bool = False) -> dict[str, Any]:
    return dict(
        require_rust_binding("read_pending_action_store")(
            str(_pending_actions_path()),
            str(_legacy_telegram_pending_actions_path()) if include_legacy else None,
        )
    )


def _entry_from_notification(
    notification: Notification, *, now: float
) -> dict[str, Any] | None:
    entry = require_rust_binding("pending_action_from_notification")(
        asdict(notification), now
    )
    return dict(entry) if entry is not None else None


def _state_for_notification(
    notification: Notification,
    pending: Mapping[str, Any] | None,
    now: float,
) -> str:
    if notification.action not in _ACTION_KIND_BY_NOTIFICATION_ACTION:
        return "unsupported"
    if gate_notification_is_terminal(notification):
        return "already_handled"
    if _required_target_missing(notification):
        return "missing_target"
    if pending is not None:
        if pending.get("state") == "already_handled":
            return "already_handled"
        if (
            pending.get("state") == "stale"
            or float(pending.get("stale_deadline_unix", 0.0)) <= now
        ):
            return "stale"
    elif _notification_is_stale(notification, now):
        return "stale"
    return "available"


def _notification_is_stale(notification: Notification, now: float) -> bool:
    try:
        timestamp = datetime.fromisoformat(notification.timestamp)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        from sase.core.time import get_timezone

        timestamp = timestamp.replace(tzinfo=get_timezone())
    return timestamp.timestamp() + STALE_THRESHOLD_SECONDS <= now


def gate_notification_is_terminal(notification: Notification) -> bool:
    """Return whether a gate notification's bundle reached a terminal state."""
    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None:
        return False
    if bundle.response.exists() or bundle.cancellation.exists():
        return True
    if (
        notification.action == "PlanApproval"
        and (bundle.root / "plan_approved.marker").exists()
    ):
        return True
    return bundle.root.is_dir() and not bundle.request.exists()


def _required_target_missing(notification: Notification) -> bool:
    from sase.notification_gates.paths import resolve_notification_bundle
    from sase.notification_gates.registry import adapter_for_action

    if adapter_for_action(notification.action) is None:
        return False
    return resolve_notification_bundle(notification) is None


def upsert_transport_action(
    action_id: str,
    record: Mapping[str, Any],
    *,
    transport: str,
    path: Path | str | None = None,
    now: float | None = None,
) -> None:
    """Store a callback record without extending its original lifecycle."""
    _transport_operation(
        "upsert",
        path=path,
        now=now,
        include_legacy=True,
        identifier=action_id,
        transport=transport,
        record=dict(record),
    )


def get_transport_action(
    action_id: str,
    *,
    transport: str,
    path: Path | str | None = None,
    include_legacy: bool = False,
) -> dict[str, Any] | None:
    """Read an exact callback identity, including records awaiting terminal cleanup."""
    return list_transport_actions(
        transport=transport, path=path, include_legacy=include_legacy
    ).get(action_id)


def list_transport_actions(
    *,
    transport: str,
    path: Path | str | None = None,
    include_legacy: bool = False,
) -> dict[str, Any]:
    """Read the transport view; leave both source stores unchanged."""
    return dict(
        _transport_operation(
            "list", transport=transport, path=path, include_legacy=include_legacy
        )
    )


def remove_transport_action(
    action_id: str,
    *,
    transport: str,
    path: Path | str | None = None,
) -> bool:
    """Retire a callback while retaining gate state and other transports."""
    return bool(
        _transport_operation(
            "remove",
            identifier=action_id,
            transport=transport,
            path=path,
            include_legacy=True,
        )
    )


def cleanup_transport_actions(
    *,
    transport: str,
    path: Path | str | None = None,
    now: float | None = None,
) -> list[str]:
    """Retire only expired callbacks belonging to this transport."""
    return list(
        _transport_operation(
            "cleanup", transport=transport, path=path, now=now, include_legacy=True
        )
    )


def _transport_operation(
    operation: str,
    *,
    path: Path | str | None = None,
    now: float | None = None,
    include_legacy: bool = False,
    **fields: Any,
) -> Any:
    return require_rust_binding("pending_action_transport")(
        {
            "operation": operation,
            "path": str(path if path is not None else _pending_actions_path()),
            "legacy_path": str(_legacy_telegram_pending_actions_path())
            if include_legacy
            else None,
            "now_unix": time.time() if now is None else now,
            **fields,
        }
    )


__all__ = [
    "upsert_transport_action",
    "remove_transport_action",
    "list_transport_actions",
    "get_transport_action",
    "cleanup_transport_actions",
    "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
    "PENDING_ACTIONS_PATH",
    "action_state_for_notification",
    "gate_notification_is_terminal",
    "mark_already_handled",
    "mark_plan_approval_auto_handled",
    "merge_transport_record",
    "read_pending_action_store",
    "register_notification",
    "resolve_prefix",
    "unregister_notification",
]
