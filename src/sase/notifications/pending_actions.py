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
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.atomic_temp import reap_stale_atomic_temps
from sase.core.paths import sase_subdir
from sase.notification_gates.registry import adapter_for_kind, registered_gate_kinds
from sase.notifications.models import Notification

PENDING_ACTIONS_PATH: Path | None = None
LEGACY_TELEGRAM_PENDING_ACTIONS_PATH: Path | None = None
PENDING_ACTION_SCHEMA_VERSION = 2
PENDING_ACTION_PREFIX_LEN = 8
STALE_THRESHOLD_SECONDS = 24 * 60 * 60

_ACTION_KIND_BY_NOTIFICATION_ACTION = {
    adapter.action: adapter.pending_action_kind
    for adapter in (adapter_for_kind(kind) for kind in registered_gate_kinds())
}
_ACTION_KIND_BY_NOTIFICATION_ACTION["memory_review"] = "memory_review"


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
        if isinstance(entry, dict) and entry.get("notification_id")
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
    ``chat_id`` and ``message_id``. An existing record for ``transport`` is
    replaced; otherwise the record is appended. Returns ``True`` when an entry
    was updated, ``False`` when no matching action exists.
    """
    current = time.time() if now is None else now
    with _locked_store() as store:
        key = _find_entry_key(store, notification_id)
        if key is None:
            return False
        entry = store["actions"][key]
        transports = list(entry.get("transports") or [])
        for item in transports:
            if isinstance(item, dict) and item.get("transport") == transport:
                item["record"] = dict(record)
                break
        else:
            transports.append({"transport": transport, "record": dict(record)})
        entry["transports"] = transports
        entry["updated_at_unix"] = current
        return True


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
    current = time.time() if now is None else now
    with _locked_store() as store:
        key = _find_entry_key(store, notification_id)
        if key is None:
            return False
        _apply_handled(store["actions"][key], source=source, action=action, now=current)
        return True


def unregister_notification(notification_id: str) -> bool:
    """Remove a gate action during creation compensation."""
    with _locked_store() as store:
        key = _find_entry_key(store, notification_id)
        if key is None:
            return False
        del store["actions"][key]
        return True


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
    current = time.time() if now is None else now
    with _locked_store() as store:
        actions = store["actions"]
        # Build a legacy-merged view so legacy-only Telegram records can match,
        # without persisting unrelated legacy rows into the shared store.
        merged = dict(actions)
        _merge_legacy_telegram({"actions": merged})
        marked: list[str] = []
        for key, entry in merged.items():
            if not isinstance(entry, dict) or entry.get("action") not in {
                "PlanApproval",
                "EpicApproval",
            }:
                continue
            if not _plan_identity_matches(
                entry,
                plan_file=plan_file,
                agent_timestamp=agent_timestamp,
                agent_root_timestamp=agent_root_timestamp,
                agent_name=agent_name,
            ):
                continue
            _apply_handled(entry, source=source, action=action, now=current)
            # Persist only the matched entry (promoting legacy-only rows).
            actions[key] = entry
            notification_id = entry.get("notification_id")
            if isinstance(notification_id, str):
                marked.append(notification_id)
        return marked


def _load_store(*, include_legacy: bool = False) -> dict[str, Any]:
    """Load the shared pending-action store."""
    store = _load_json(_pending_actions_path())
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


def _merge_legacy_telegram(store: dict[str, Any]) -> None:
    legacy = _load_json(_legacy_telegram_pending_actions_path())
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


def _find_entry_key(store: Mapping[str, Any], identifier: str) -> str | None:
    """Return the actions key for a full notification id or unique prefix."""
    actions = store.get("actions", {})
    if identifier in actions:
        return identifier
    for key, entry in actions.items():
        if isinstance(entry, dict) and entry.get("notification_id") == identifier:
            return key
    prefix_matches = [
        key
        for key, entry in actions.items()
        if isinstance(entry, dict)
        and str(entry.get("notification_id", "")).startswith(identifier)
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def _apply_handled(
    entry: dict[str, Any],
    *,
    source: str,
    action: str | None,
    now: float,
) -> None:
    """Stamp ``entry`` with already-handled state and audit metadata."""
    entry["state"] = "already_handled"
    entry["handled_source"] = source
    entry["handled_at_unix"] = now
    entry["updated_at_unix"] = now
    if action is not None:
        entry["handled_action"] = action


def _plan_identity_matches(
    entry: Mapping[str, Any],
    *,
    plan_file: str,
    agent_timestamp: str | None,
    agent_root_timestamp: str | None,
    agent_name: str | None,
) -> bool:
    """Return True when a PlanApproval entry matches a plan file plus identity."""
    if not _entry_plan_file_matches(entry, plan_file):
        return False
    action_data = entry.get("action_data")
    action_data = action_data if isinstance(action_data, Mapping) else {}
    identity_pairs = [
        ("agent_timestamp", agent_timestamp),
        ("agent_root_timestamp", agent_root_timestamp),
        ("agent_name", agent_name),
    ]
    provided = [(field, value) for field, value in identity_pairs if value]
    if not provided:
        return False
    return any(action_data.get(field) == value for field, value in provided)


def _entry_plan_file_matches(entry: Mapping[str, Any], plan_file: str) -> bool:
    files = entry.get("files")
    if isinstance(files, list) and plan_file in files:
        return True
    action_data = entry.get("action_data")
    if isinstance(action_data, Mapping) and action_data.get("plan_file") == plan_file:
        return True
    return entry.get("plan_file") == plan_file


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
    store_path = _pending_actions_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store_path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            store = _load_store()
            yield store
            _write_store(store)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_store(store: dict[str, Any]) -> None:
    store_path = _pending_actions_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    reap_stale_atomic_temps(store_path)
    fd, tmp_path = tempfile.mkstemp(
        dir=store_path.parent,
        prefix=f".{store_path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, store_path)
        _fsync_dir(store_path.parent)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


__all__ = [
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
