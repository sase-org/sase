"""Shared host pending-action storage for notification transports."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notifications.models import Notification

PENDING_ACTIONS_PATH = Path.home() / ".sase" / "pending_actions" / "actions.json"
LEGACY_TELEGRAM_PENDING_ACTIONS_PATH = (
    Path.home() / ".sase" / "telegram" / "pending_actions.json"
)
PENDING_ACTION_SCHEMA_VERSION = 1
PENDING_ACTION_PREFIX_LEN = 8
STALE_THRESHOLD_SECONDS = 24 * 60 * 60

_ACTION_KIND_BY_NOTIFICATION_ACTION = {
    "PlanApproval": "plan_approval",
    "HITL": "hitl",
    "UserQuestion": "user_question",
}


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class PrefixResolution:
    notification_id: str
    prefix: str
    prefix_len: int
    resolution: str


def register_notification(
    notification: Notification, *, now: float | None = None
) -> None:
    """Register an actionable notification in the shared pending-action store."""
    entry = _entry_from_notification(
        notification, now=time.time() if now is None else now
    )
    if entry is None:
        return
    with _locked_store() as store:
        existing = store["actions"].get(entry["prefix"])
        if isinstance(existing, dict):
            entry["created_at_unix"] = existing.get(
                "created_at_unix", entry["created_at_unix"]
            )
            transports = list(existing.get("transports") or [])
            for transport in entry["transports"]:
                if not any(
                    item.get("transport") == transport["transport"]
                    for item in transports
                    if isinstance(item, dict)
                ):
                    transports.append(transport)
            entry["transports"] = transports
        store["actions"][entry["prefix"]] = entry


def action_state_for_notification(
    notification: Notification, *, now: float | None = None
) -> str:
    """Return the mobile action state for a notification without mutating it."""
    current = time.time() if now is None else now
    store = load_store(include_legacy=True)
    pending = next(
        (
            entry
            for entry in store.get("actions", {}).values()
            if isinstance(entry, dict)
            and entry.get("notification_id") == notification.id
        ),
        None,
    )
    return _state_for_notification(notification, pending, current)


def resolve_prefix(prefix: str, *, include_legacy: bool = True) -> PrefixResolution:
    """Resolve a full notification id or unique notification-id prefix."""
    store = load_store(include_legacy=include_legacy)
    ids = [
        str(entry.get("notification_id"))
        for entry in store.get("actions", {}).values()
        if isinstance(entry, dict) and entry.get("notification_id")
    ]
    exact = [notification_id for notification_id in ids if notification_id == prefix]
    if len(exact) == 1:
        return PrefixResolution(prefix, prefix, len(prefix), "exact")
    if len(exact) > 1:
        return PrefixResolution(prefix, prefix, len(prefix), "duplicate_full_id")
    matches = [
        notification_id for notification_id in ids if notification_id.startswith(prefix)
    ]
    if len(matches) == 1:
        return PrefixResolution(matches[0], prefix, len(prefix), "unique_prefix")
    if not matches:
        return PrefixResolution("", prefix, len(prefix), "missing")
    return PrefixResolution("", prefix, len(prefix), "ambiguous_prefix")


def cleanup_stale(*, now: float | None = None) -> list[str]:
    """Remove stale pending entries and return removed prefixes."""
    current = time.time() if now is None else now
    with _locked_store() as store:
        actions = store["actions"]
        stale = [
            prefix
            for prefix, entry in actions.items()
            if isinstance(entry, dict)
            and float(entry.get("stale_deadline_unix", 0.0)) <= current
        ]
        for prefix in stale:
            actions.pop(prefix, None)
        return stale


def load_store(*, include_legacy: bool = False) -> dict[str, Any]:
    """Load the shared pending-action store."""
    store = _load_json(PENDING_ACTIONS_PATH)
    if not isinstance(store, dict) or "actions" not in store:
        store = _empty_store()
    if not isinstance(store.get("actions"), dict):
        store["actions"] = {}
    if include_legacy:
        _merge_legacy_telegram(store)
    return store


def _entry_from_notification(
    notification: Notification, *, now: float
) -> dict[str, Any] | None:
    action = notification.action
    if action not in _ACTION_KIND_BY_NOTIFICATION_ACTION:
        return None
    prefix = notification.id[:PENDING_ACTION_PREFIX_LEN]
    return {
        "schema_version": PENDING_ACTION_SCHEMA_VERSION,
        "prefix": prefix,
        "notification_id": notification.id,
        "action_kind": _ACTION_KIND_BY_NOTIFICATION_ACTION[action],
        "action": action,
        "action_data": dict(notification.action_data),
        "files": list(notification.files),
        "created_at_unix": now,
        "updated_at_unix": now,
        "stale_deadline_unix": now + STALE_THRESHOLD_SECONDS,
        "transports": [{"transport": "notification_store", "record": {}}],
        "state": "available",
    }


def _state_for_notification(
    notification: Notification,
    pending: Mapping[str, Any] | None,
    now: float,
) -> str:
    if notification.action not in _ACTION_KIND_BY_NOTIFICATION_ACTION:
        return "unsupported"
    if _externally_handled(notification):
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
    return "available"


def _externally_handled(notification: Notification) -> bool:
    if notification.action == "PlanApproval":
        response_dir = _action_path(notification, "response_dir")
        if response_dir is None:
            return False
        return (
            (response_dir / "plan_response.json").exists()
            or (response_dir / "plan_approved.marker").exists()
            or (
                response_dir.is_dir()
                and not (response_dir / "plan_request.json").exists()
            )
        )
    if notification.action == "HITL":
        artifacts_dir = _action_path(notification, "artifacts_dir")
        if artifacts_dir is None:
            return False
        return (artifacts_dir / "hitl_response.json").exists() or (
            artifacts_dir.is_dir()
            and not (artifacts_dir / "hitl_request.json").exists()
        )
    if notification.action == "UserQuestion":
        response_dir = _action_path(notification, "response_dir")
        if response_dir is None:
            return False
        return (response_dir / "question_response.json").exists() or (
            response_dir.is_dir()
            and not (response_dir / "question_request.json").exists()
        )
    return False


def _required_target_missing(notification: Notification) -> bool:
    if notification.action in {"PlanApproval", "UserQuestion"}:
        return _action_path(notification, "response_dir") is None
    if notification.action == "HITL":
        return _action_path(notification, "artifacts_dir") is None
    return False


def _action_path(notification: Notification, key: str) -> Path | None:
    value = notification.action_data.get(key)
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


def _merge_legacy_telegram(store: dict[str, Any]) -> None:
    legacy = _load_json(LEGACY_TELEGRAM_PENDING_ACTIONS_PATH)
    if not isinstance(legacy, dict):
        return
    actions = store["actions"]
    for prefix, raw_entry in legacy.items():
        if prefix in actions or not isinstance(raw_entry, dict):
            continue
        notification_id = raw_entry.get("notification_id")
        action = raw_entry.get("action")
        if (
            not isinstance(notification_id, str)
            or action not in _ACTION_KIND_BY_NOTIFICATION_ACTION
        ):
            continue
        record = {
            key: raw_entry[key] for key in ("chat_id", "message_id") if key in raw_entry
        }
        created_at = float(raw_entry.get("created_at", time.time()))
        actions[prefix] = {
            "schema_version": PENDING_ACTION_SCHEMA_VERSION,
            "prefix": prefix,
            "notification_id": notification_id,
            "action_kind": _ACTION_KIND_BY_NOTIFICATION_ACTION[action],
            "action": action,
            "action_data": dict(raw_entry.get("action_data") or {}),
            "files": [raw_entry["plan_file"]] if raw_entry.get("plan_file") else [],
            "created_at_unix": created_at,
            "updated_at_unix": created_at,
            "stale_deadline_unix": created_at + STALE_THRESHOLD_SECONDS,
            "transports": [{"transport": "telegram_legacy", "record": record}],
            "state": "available",
        }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _empty_store() -> dict[str, Any]:
    return {"schema_version": PENDING_ACTION_SCHEMA_VERSION, "actions": {}}


@contextmanager
def _locked_store() -> Any:
    PENDING_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = PENDING_ACTIONS_PATH.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            store = load_store()
            yield store
            _write_store(store)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_store(store: dict[str, Any]) -> None:
    PENDING_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=PENDING_ACTIONS_PATH.parent,
        prefix=f".{PENDING_ACTIONS_PATH.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, PENDING_ACTIONS_PATH)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


__all__ = [
    "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
    "PENDING_ACTIONS_PATH",
    "PrefixResolution",
    "action_state_for_notification",
    "cleanup_stale",
    "load_store",
    "register_notification",
    "resolve_prefix",
]
