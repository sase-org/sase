"""Project remote fleet attention inventory into the durable notification inbox."""

from __future__ import annotations

import copy
import dataclasses
import json
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
    GATE_PANEL_ACTION_DATA_KEY,
    GATE_PANEL_ICON_ACTION_DATA_KEY,
    GATE_TITLE_ACTION_DATA_KEY,
)
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import load_notifications, rewrite_notifications

from .federation import (
    FEDERATION_IPC_SCHEMA_VERSION,
    build_federation_facade,
    load_federation_config,
)

REMOTE_ATTENTION_NOTIFICATION_ACTION = "RemoteAttention"
REMOTE_ATTENTION_NOTIFICATION_PANEL = "attention"
REMOTE_ATTENTION_NOTIFICATION_SENDER = "remote-attention"
REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY = "remote_attention_entry_json"
REMOTE_ATTENTION_ALIAS_ACTION_DATA_KEY = "remote_attention_alias"
REMOTE_ATTENTION_ORIGIN_ACTION_DATA_KEY = "remote_attention_origin_installation_id"
REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY = "remote_attention_request_id"
REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY = "remote_attention_revision"
REMOTE_ATTENTION_KIND_ACTION_DATA_KEY = "remote_attention_kind"

_FLEET_SCHEMA_VERSION = 1
_INBOX_PAGE_LIMIT = 100


@dataclass(frozen=True)
class _AttentionInboxReconcileOutcome:
    """Mutation summary for one remote attention inventory reconciliation."""

    pending: int = 0
    created: int = 0
    updated: int = 0
    dismissed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.dismissed)


@dataclass(frozen=True)
class _InventoryEntry:
    alias: str
    origin_installation_id: str
    request_id: str
    revision: str
    entry: dict[str, Any]
    observed_at_unix: float | None

    @property
    def base_key(self) -> tuple[str, str]:
        return (self.origin_installation_id, self.request_id)

    @property
    def dedup_key(self) -> str:
        return _dedup_key(
            origin_installation_id=self.origin_installation_id,
            request_id=self.request_id,
            revision=self.revision,
        )


@dataclass(frozen=True)
class _CoveredHost:
    alias: str
    origin_installation_id: str | None
    can_settle_absences: bool


def fetch_remote_attention_inventory(
    *,
    cache_only: bool = False,
    timeout_seconds: float | None = None,
    limit: int = _INBOX_PAGE_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Fetch every authorized pending remote attention request.

    Unlike the row-scoped attention fetch, this call is intentionally
    independent of followed logical keys. With no configured machines the
    federation facade stays disabled and no worker is started.
    """
    config = load_federation_config()
    if not config.enabled:
        return {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "operation": "attention_inventory",
            "disabled": True,
            "hosts": [],
        }
    request: dict[str, Any] = {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "limit": int(limit),
    }
    if cursor:
        request["cursor"] = cursor
    return build_federation_facade(config).attention_inventory_sync(
        request,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds or config.worker.request_timeout_seconds,
    )


def reconcile_remote_attention_inbox(
    response: Mapping[str, Any],
    *,
    now_unix: float | None = None,
) -> _AttentionInboxReconcileOutcome:
    """Make durable notification rows match one global attention inventory."""
    entries, covered_hosts = _inventory_entries(response)
    if not entries and not covered_hosts:
        return _AttentionInboxReconcileOutcome()

    now = time.time() if now_unix is None else now_unix
    rows = load_notifications(include_dismissed=True)
    rows_by_dedup = {
        row.dedup_key: row
        for row in rows
        if row.sender == REMOTE_ATTENTION_NOTIFICATION_SENDER and row.dedup_key
    }
    output = list(rows)
    created = 0
    updated = 0
    pending_dedup_keys = {entry.dedup_key for entry in entries}
    pending_base_keys = {entry.base_key for entry in entries}

    for entry in entries:
        notification = _notification_for_entry(entry, now_unix=now)
        existing = rows_by_dedup.get(entry.dedup_key)
        if existing is None:
            output.append(notification)
            rows_by_dedup[entry.dedup_key] = notification
            created += 1
            continue
        refreshed = _refresh_existing_notification(existing, notification)
        if refreshed != existing:
            _replace_notification(output, existing.id, refreshed)
            rows_by_dedup[entry.dedup_key] = refreshed
            updated += 1

    dismissed = 0
    for index, row in enumerate(tuple(output)):
        if row.sender != REMOTE_ATTENTION_NOTIFICATION_SENDER:
            continue
        if row.dedup_key in pending_dedup_keys:
            continue
        row_identity = _notification_identity(row)
        if row_identity is None:
            continue
        origin, request_id, _revision = row_identity
        if (origin, request_id) in pending_base_keys:
            if not row.dismissed:
                output[index] = dataclasses.replace(row, dismissed=True)
                dismissed += 1
            continue
        if _covered_by_settling_host(row, covered_hosts):
            if not row.dismissed:
                output[index] = dataclasses.replace(row, dismissed=True)
                dismissed += 1

    outcome = _AttentionInboxReconcileOutcome(
        pending=len(entries),
        created=created,
        updated=updated,
        dismissed=dismissed,
    )
    if outcome.changed:
        rewrite_notifications(output)
    return outcome


def remote_attention_from_notification(
    notification: Notification,
) -> tuple[str, dict[str, Any]] | None:
    """Decode the modal payload carried by a remote-attention notification."""
    if notification.action != REMOTE_ATTENTION_NOTIFICATION_ACTION:
        return None
    data = notification.action_data or {}
    alias = data.get(REMOTE_ATTENTION_ALIAS_ACTION_DATA_KEY)
    raw_entry = data.get(REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY)
    if not alias or not raw_entry:
        return None
    try:
        entry = json.loads(raw_entry)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    return alias, entry


def _inventory_entries(
    response: Mapping[str, Any],
) -> tuple[list[_InventoryEntry], list[_CoveredHost]]:
    entries: list[_InventoryEntry] = []
    covered_hosts: list[_CoveredHost] = []
    hosts = response.get("hosts")
    if not isinstance(hosts, Iterable) or isinstance(hosts, (str, bytes, bytearray)):
        return entries, covered_hosts
    for host in hosts:
        if not isinstance(host, Mapping):
            continue
        alias = _string(host.get("alias")) or "remote"
        host_origin = _string(host.get("installation_id")) or _string(
            host.get("origin_installation_id")
        )
        if isinstance(host.get("error"), Mapping):
            continue
        payload = host.get("payload")
        if not isinstance(payload, Mapping):
            continue
        page = payload.get("page")
        raw_entries = None
        if isinstance(page, Mapping):
            raw_entries = page.get("entries")
        if raw_entries is None:
            raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            continue
        covered_hosts.append(
            _CoveredHost(
                alias=alias,
                origin_installation_id=host_origin,
                can_settle_absences=_payload_is_fresh_complete(payload, host),
            )
        )
        observed = _float(payload.get("observed_at_unix"))
        if observed is None:
            observed = _float(response.get("observed_at_unix"))
        for raw in raw_entries:
            entry = _coerce_pending_entry(
                raw,
                alias=alias,
                host_origin_installation_id=host_origin,
                observed_at_unix=observed,
            )
            if entry is not None:
                entries.append(entry)
    return entries, covered_hosts


def _coerce_pending_entry(
    raw: object,
    *,
    alias: str,
    host_origin_installation_id: str | None,
    observed_at_unix: float | None,
) -> _InventoryEntry | None:
    if not isinstance(raw, Mapping):
        return None
    if raw.get("state") != "pending":
        return None
    request_key = raw.get("request_key")
    if not isinstance(request_key, Mapping):
        return None
    request_id = _string(request_key.get("request_id"))
    if not request_id:
        return None
    origin = _string(request_key.get("origin_installation_id"))
    if not origin:
        origin = host_origin_installation_id or alias
    revision = _revision_string(raw.get("revision"))
    if not revision:
        return None
    entry = copy.deepcopy(dict(raw))
    entry.setdefault("observed_at_unix", observed_at_unix)
    return _InventoryEntry(
        alias=alias,
        origin_installation_id=origin,
        request_id=request_id,
        revision=revision,
        entry=entry,
        observed_at_unix=observed_at_unix,
    )


def _notification_for_entry(
    entry: _InventoryEntry,
    *,
    now_unix: float,
) -> Notification:
    kind = _string(entry.entry.get("kind")) or "gate"
    title = _string(entry.entry.get("title")) or (
        "Remote question" if kind == "question" else "Remote gate"
    )
    summary = _string(entry.entry.get("summary"))
    timestamp = _iso_from_unix(entry.observed_at_unix or now_unix)
    notes = [f"{entry.alias}: {title}"]
    if summary:
        notes.append(summary)
    if kind == "question":
        notes.append("Remote question awaiting your answer")
    else:
        notes.append("Remote gate awaiting your decision")
    action_data = {
        GATE_PANEL_ACTION_DATA_KEY: REMOTE_ATTENTION_NOTIFICATION_PANEL,
        GATE_PANEL_ICON_ACTION_DATA_KEY: "!",
        GATE_CHIP_GLYPH_ACTION_DATA_KEY: "?",
        GATE_CHIP_LABEL_ACTION_DATA_KEY: entry.alias,
        GATE_CHIP_COLOR_ACTION_DATA_KEY: "#87D7FF",
        GATE_TITLE_ACTION_DATA_KEY: title,
        REMOTE_ATTENTION_ALIAS_ACTION_DATA_KEY: entry.alias,
        REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY: json.dumps(
            entry.entry,
            sort_keys=True,
            separators=(",", ":"),
        ),
        REMOTE_ATTENTION_ORIGIN_ACTION_DATA_KEY: entry.origin_installation_id,
        REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY: entry.request_id,
        REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY: entry.revision,
        REMOTE_ATTENTION_KIND_ACTION_DATA_KEY: kind,
    }
    return Notification(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"sase:{entry.dedup_key}")),
        timestamp=timestamp,
        sender=REMOTE_ATTENTION_NOTIFICATION_SENDER,
        icon="?" if kind == "question" else "!",
        color="#87D7FF",
        notes=notes,
        tags=normalize_notification_tags(("attention", entry.alias, kind)),
        action=REMOTE_ATTENTION_NOTIFICATION_ACTION,
        action_data=action_data,
        read=False,
        dismissed=False,
        silent=False,
        dedup_key=entry.dedup_key,
    )


def _refresh_existing_notification(
    existing: Notification,
    incoming: Notification,
) -> Notification:
    return dataclasses.replace(
        existing,
        icon=incoming.icon,
        color=incoming.color,
        notes=incoming.notes,
        tags=incoming.tags,
        action=incoming.action,
        action_data=incoming.action_data,
        read=False,
        dismissed=False,
        silent=False,
    )


def _replace_notification(
    rows: list[Notification],
    notification_id: str,
    replacement: Notification,
) -> None:
    for index, row in enumerate(rows):
        if row.id == notification_id:
            rows[index] = replacement
            return


def _notification_identity(
    notification: Notification,
) -> tuple[str, str, str] | None:
    data = notification.action_data or {}
    origin = data.get(REMOTE_ATTENTION_ORIGIN_ACTION_DATA_KEY)
    request_id = data.get(REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY)
    revision = data.get(REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY)
    if not origin or not request_id or not revision:
        return None
    return origin, request_id, revision


def _covered_by_settling_host(
    notification: Notification,
    hosts: list[_CoveredHost],
) -> bool:
    data = notification.action_data or {}
    row_origin = data.get(REMOTE_ATTENTION_ORIGIN_ACTION_DATA_KEY)
    row_alias = data.get(REMOTE_ATTENTION_ALIAS_ACTION_DATA_KEY)
    for host in hosts:
        if not host.can_settle_absences:
            continue
        if host.origin_installation_id and row_origin == host.origin_installation_id:
            return True
        if not host.origin_installation_id and row_alias == host.alias:
            return True
    return False


def _payload_is_fresh_complete(
    payload: Mapping[str, Any],
    host: Mapping[str, Any],
) -> bool:
    if str(host.get("status") or "ok") != "ok":
        return False
    if bool(host.get("cached")):
        return False
    freshness = payload.get("freshness")
    if not isinstance(freshness, Mapping):
        return True
    if str(freshness.get("freshness") or "") != "fresh":
        return False
    return not bool(freshness.get("partial"))


def _dedup_key(
    *,
    origin_installation_id: str,
    request_id: str,
    revision: str,
) -> str:
    return f"remote-attention:{origin_installation_id}:{request_id}:{revision}"


def _string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _revision_string(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iso_from_unix(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


__all__ = [
    "REMOTE_ATTENTION_ALIAS_ACTION_DATA_KEY",
    "REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY",
    "REMOTE_ATTENTION_KIND_ACTION_DATA_KEY",
    "REMOTE_ATTENTION_NOTIFICATION_ACTION",
    "REMOTE_ATTENTION_NOTIFICATION_PANEL",
    "REMOTE_ATTENTION_NOTIFICATION_SENDER",
    "REMOTE_ATTENTION_ORIGIN_ACTION_DATA_KEY",
    "REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY",
    "REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY",
    "fetch_remote_attention_inventory",
    "reconcile_remote_attention_inbox",
    "remote_attention_from_notification",
]
