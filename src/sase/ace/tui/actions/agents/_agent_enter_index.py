"""Gate-notification index and lookup helpers for Enter targets."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sase.notification_gates.registry import adapter_for_action
from sase.notifications.agent_matching import agent_matches_notification_identity

from ._agent_enter_models import GateNotificationIndex

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification

_INDEX_CACHE_REF: Any = None
_INDEX_CACHE: GateNotificationIndex | None = None


def build_gate_notification_index(snapshot: Any) -> GateNotificationIndex:
    """Prefilter *snapshot*'s notifications into a gate lookup index.

    The result is cached per snapshot object: repeated calls with the same
    object return the same index without rebuilding. Any other object
    rebuilds. Accepts the ``AceNotificationSnapshot`` shape (``.notifications``)
    or a plain sequence of notifications.
    """
    global _INDEX_CACHE_REF, _INDEX_CACHE
    if snapshot is _INDEX_CACHE_REF and _INDEX_CACHE is not None:
        return _INDEX_CACHE
    notifications: Sequence[Notification]
    if isinstance(snapshot, (list, tuple)):
        notifications = snapshot
    else:
        notifications = getattr(snapshot, "notifications", None) or ()
    by_id: dict[str, Notification] = {}
    by_bundle_path: dict[str, Notification] = {}
    by_raw_suffix: dict[str, list[Notification]] = {}
    by_request_id: dict[str, Notification] = {}
    gate_notifications: list[Notification] = []
    for notification in notifications:
        by_id.setdefault(notification.id, notification)
        bundle_path = notification.action_data.get("bundle_path")
        if bundle_path:
            by_bundle_path.setdefault(str(bundle_path), notification)
        raw_suffix = notification.action_data.get("raw_suffix")
        if raw_suffix:
            by_raw_suffix.setdefault(str(raw_suffix), []).append(notification)
        if adapter_for_action(notification.action) is not None:
            gate_notifications.append(notification)
            request_id = notification.action_data.get("request_id")
            if request_id:
                by_request_id.setdefault(str(request_id), notification)
    index = GateNotificationIndex(
        by_id=by_id,
        by_bundle_path=by_bundle_path,
        by_raw_suffix=by_raw_suffix,
        by_request_id=by_request_id,
        gate_notifications=tuple(gate_notifications),
    )
    _INDEX_CACHE_REF = snapshot
    _INDEX_CACHE = index
    return index


def empty_gate_notification_index() -> GateNotificationIndex:
    """Return an index with no notifications (snapshot cache still empty)."""
    return GateNotificationIndex()


def linked_notification(
    row: Agent, index: GateNotificationIndex
) -> Notification | None:
    notification_id = getattr(row, "gate_notification_id", None)
    if notification_id and notification_id in index.by_id:
        return index.by_id[notification_id]
    bundle_path = getattr(row, "gate_bundle_path", None)
    if bundle_path and str(bundle_path) in index.by_bundle_path:
        return index.by_bundle_path[str(bundle_path)]
    gate_id = getattr(row, "gate_id", None)
    if isinstance(gate_id, str) and gate_id and gate_id in index.by_request_id:
        return index.by_request_id[gate_id]
    return None


def identity_matched_gate_notifications(
    candidates: Sequence[Agent], index: GateNotificationIndex
) -> list[Notification]:
    matched: list[Notification] = []
    for notification in index.gate_notifications:
        for candidate in candidates:
            try:
                if agent_matches_notification_identity(candidate, notification):
                    matched.append(notification)
                    break
            except Exception:
                continue
    return matched


__all__ = [
    "GateNotificationIndex",
    "identity_matched_gate_notifications",
    "linked_notification",
    "build_gate_notification_index",
    "empty_gate_notification_index",
]
