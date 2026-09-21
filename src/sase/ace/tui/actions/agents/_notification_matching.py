"""Notification classification: suffixes, predicates, keys, and matching."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification


SETTLEMENT_NOTIFICATION_SENDERS = frozenset({"epic-launch", "monitor-settlement"})
PENDING_GATE_REFRESH_ACTIONS = frozenset(
    {"PlanApproval", "EpicApproval", "UserQuestion"}
)
FAMILY_ROOT_SUFFIX_KEYS = (
    "family_root_suffix",
    "family_root_raw_suffix",
    "agent_root_timestamp",
    "root_raw_suffix",
)


def normalized_suffix(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    from ...models._timestamps import normalize_to_14_digit

    return normalize_to_14_digit(value.strip())


def notification_raw_suffix(notification: Notification) -> str | None:
    return normalized_suffix(notification.action_data.get("raw_suffix"))


def notification_family_root_suffix(notification: Notification) -> str | None:
    for key in FAMILY_ROOT_SUFFIX_KEYS:
        suffix = normalized_suffix(notification.action_data.get(key))
        if suffix:
            return suffix
    return None


def pending_gate_notification_suffixes(notification: Notification) -> list[str]:
    """Return gate-member, planner, and family-root suffixes in that order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for value in (
        notification_raw_suffix(notification),
        normalized_suffix(notification.action_data.get("agent_timestamp")),
        notification_family_root_suffix(notification),
    ):
        if value is None or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def is_active_agent_completion_notification(notification: Notification) -> bool:
    """Return True for active agent completion notifications."""
    if notification.sender != "user-agent":
        return False
    if notification.action not in ("JumpToAgent", "ViewErrorReport"):
        return False
    return not notification.dismissed


def is_active_agent_settlement_notification(notification: Notification) -> bool:
    """Return True for active settlement notifications with row identity."""
    if notification.dismissed:
        return False
    data = notification.action_data
    raw_suffix = notification_raw_suffix(notification)
    if not data.get("cl_name") or raw_suffix is None:
        return False
    if notification.sender in SETTLEMENT_NOTIFICATION_SENDERS:
        return True
    if not is_active_agent_completion_notification(notification):
        return False
    root_suffix = notification_family_root_suffix(notification)
    return root_suffix is not None and root_suffix != raw_suffix


def is_active_pending_gate_refresh_notification(notification: Notification) -> bool:
    """Return True for an active pending-review gate notification.

    Sibling of the completion and settlement predicates. Plan/epic/question
    arrivals need an exact family-chain refresh on the toast tick; they are
    not settlement senders.
    """
    if notification.dismissed:
        return False
    return notification.action in PENDING_GATE_REFRESH_ACTIONS


def is_active_agent_refresh_notification(notification: Notification) -> bool:
    """Return True when a new notification can drive an exact Agents refresh."""
    return (
        is_active_agent_completion_notification(notification)
        or is_active_agent_settlement_notification(notification)
        or is_active_pending_gate_refresh_notification(notification)
    )


def active_completion_agent_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active completion notifications.

    A completion notification is identified by ``sender == "user-agent"`` and
    ``action`` in ``{"JumpToAgent", "ViewErrorReport"}`` with ``cl_name``
    present in ``action_data``. ``raw_suffix`` may be absent when the writer
    did not record one, so those rows match agents by ``cl_name`` only.

    "Active" means not yet dismissed. Default snapshots already omit
    dismissed rows, but the predicate is enforced here as well so callers
    that pass ``include_dismissed=True`` get the right projection. Silent
    rows still count: per the one-to-one contract, dismissed status is
    what gates the row, not indicator visibility.
    """
    keys: set[tuple[str, str | None]] = set()
    for n in notifications:
        if not is_active_agent_completion_notification(n):
            continue
        cl_name = n.action_data.get("cl_name")
        if not cl_name:
            continue
        raw_suffix = n.action_data.get("raw_suffix") or None
        keys.add((cl_name, raw_suffix))
    return keys


def active_row_owned_notification_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active row-owned notifications.

    Union of :func:`active_completion_agent_keys` and the exact keys of active
    host-owned settlement rows (``epic-launch`` / ``monitor-settlement``). The
    settlement half mirrors :func:`agent_settlement_notification_matches_agent`:
    exact match only, no ``cl_name``-only fallback.
    """
    keys = active_completion_agent_keys(notifications)
    for n in notifications:
        if n.dismissed:
            continue
        if n.sender not in SETTLEMENT_NOTIFICATION_SENDERS:
            continue
        cl_name = n.action_data.get("cl_name")
        raw_suffix = n.action_data.get("raw_suffix")
        if not cl_name or not raw_suffix:
            continue
        keys.add((cl_name, raw_suffix))
    return keys


def agent_completion_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* targets the supplied agent key."""
    if not is_active_agent_completion_notification(notification):
        return False
    notification_cl_name = notification.action_data.get("cl_name")
    if not notification_cl_name or notification_cl_name != cl_name:
        return False
    notification_raw_suffix = notification.action_data.get("raw_suffix") or None
    return notification_raw_suffix is None or notification_raw_suffix == raw_suffix


def agent_settlement_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* is a settlement row owned by the key.

    Mirrors ``matches_agent_settlement_notification_for_agents`` in the Rust
    core: the sender must be host-owned settlement (``epic-launch`` or
    ``monitor-settlement``) and ``action_data`` must name a non-empty
    ``cl_name`` and a non-empty ``raw_suffix`` that both equal the supplied
    key. There is deliberately no ``cl_name``-only fallback: ``cl_name`` on
    these rows is the project-wide patch name, so a fallback would let
    acknowledging one agent dismiss every project-wide settlement row.
    """
    if notification.dismissed:
        return False
    if notification.sender not in SETTLEMENT_NOTIFICATION_SENDERS:
        return False
    if not cl_name or not raw_suffix:
        return False
    notification_cl_name = notification.action_data.get("cl_name")
    notification_raw_suffix = notification.action_data.get("raw_suffix")
    if not notification_cl_name or not notification_raw_suffix:
        return False
    return notification_cl_name == cl_name and notification_raw_suffix == raw_suffix


def agent_row_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* is acknowledged with the supplied row.

    Single completion-or-settlement predicate for read-ack and dismissal
    paths so the two rules stay in one place.
    """
    return agent_completion_notification_matches_agent(
        notification, cl_name=cl_name, raw_suffix=raw_suffix
    ) or agent_settlement_notification_matches_agent(
        notification, cl_name=cl_name, raw_suffix=raw_suffix
    )


def unread_notification_buckets(
    notifications: list[Notification],
) -> tuple[
    list[Notification], list[Notification], list[Notification], list[Notification]
]:
    from sase.notifications import is_error, is_priority

    unread_priority: list[Notification] = []
    unread_errors: list[Notification] = []
    unread_rest: list[Notification] = []
    unread_muted: list[Notification] = []
    for n in notifications:
        if n.read or n.silent:
            continue
        if n.muted:
            unread_muted.append(n)
        elif is_error(n):
            unread_errors.append(n)
        elif is_priority(n):
            unread_priority.append(n)
        else:
            unread_rest.append(n)
    return unread_priority, unread_errors, unread_rest, unread_muted
