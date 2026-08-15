"""Noninteractive notification state runners."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime

from sase.ops.cli import add_operation_io_flags, load_request
from sase.ops.commands.common import run_and_finish
from sase.ops.names import NOTIFY_APPLY_STATE


def add_notify_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register focused notification state commands."""
    parser = subparsers.add_parser(
        "apply-state",
        help="Apply a durable notification state change",
        description=(
            "Mark one notification read, dismissed, muted, unmuted, or snoozed. "
            "The notification id and action are positional; snooze expiry may "
            "come from the private request sidecar."
        ),
    )
    parser.add_argument("notification_id", help="Notification id to update")
    parser.add_argument(
        "action",
        choices=("dismiss", "mute", "read", "snooze", "unmute"),
        help="State change to apply",
    )
    add_operation_io_flags(parser)

    many_parser = subparsers.add_parser(
        "apply-state-many",
        help="Apply a durable notification state change to a private id set",
        description=(
            "Apply a notification state update to ids carried in the private "
            "request sidecar. This command is intended for durable ACE procs."
        ),
    )
    many_parser.add_argument(
        "action",
        choices=("dismiss", "mute", "read", "snooze", "unmute"),
        help="State change to apply",
    )
    add_operation_io_flags(many_parser)


def handle_notify_operation(args: argparse.Namespace) -> int:
    """Dispatch the notification apply-state command."""
    subcommand = getattr(args, "notify_subcommand", None)
    if subcommand == "apply-state-many":
        return run_and_finish(
            operation=NOTIFY_APPLY_STATE,
            body=lambda: _run_apply_state_many(args),
            args=args,
        )
    if subcommand != "apply-state":
        return 2
    return run_and_finish(
        operation=NOTIFY_APPLY_STATE,
        body=lambda: _run_apply_state(args),
        args=args,
    )


def _run_apply_state(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, object]]:
    from sase.notifications.store import (
        mark_dismissed,
        mark_muted,
        mark_read,
        mark_snoozed,
    )

    request = load_request(NOTIFY_APPLY_STATE, args)
    notification_id = args.notification_id
    action = args.action
    found = False
    if action == "read":
        found = mark_read(notification_id)
    elif action == "dismiss":
        found = mark_dismissed(notification_id)
    elif action == "mute":
        found = mark_muted(notification_id, muted=True)
    elif action == "unmute":
        found = mark_muted(notification_id, muted=False)
    elif action == "snooze":
        raw_until = request.payload.get("until")
        if not isinstance(raw_until, str) or not raw_until:
            return False, "snooze request payload must include until", {}
        found = mark_snoozed(notification_id, datetime.fromisoformat(raw_until))
    if not found:
        return False, f"Notification {notification_id} was not found", {}
    return (
        True,
        f"Applied {action} to {notification_id}",
        {
            "action": action,
            "ids": [notification_id],
            "matched_count": 1,
            "muted": _muted_payload(action),
            "notification_id": notification_id,
            "snooze_until": request.payload.get("until"),
        },
    )


def _run_apply_state_many(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, object]]:
    from sase.notifications.store import (
        mark_many_dismissed,
        mark_many_muted,
        mark_many_snoozed,
        mark_read,
        mark_tab_read,
    )

    request = load_request(NOTIFY_APPLY_STATE, args, required=True)
    action = args.action
    raw_ids = request.payload.get("ids")
    ids = tuple(str(item) for item in raw_ids) if isinstance(raw_ids, list) else ()
    matched = 0
    snooze_until: str | None = None
    if action == "read" and isinstance(request.payload.get("tab_key"), str):
        matched = int(mark_tab_read(str(request.payload["tab_key"])))
    elif action == "read":
        matched = sum(1 for notification_id in ids if mark_read(notification_id))
    elif action == "dismiss":
        matched = mark_many_dismissed(ids)
    elif action == "mute":
        matched = mark_many_muted(ids, True)
    elif action == "unmute":
        matched = mark_many_muted(ids, False)
    elif action == "snooze":
        raw_until = request.payload.get("until")
        if not isinstance(raw_until, str) or not raw_until:
            return False, "snooze request payload must include until", {}
        snooze_until = raw_until
        matched = mark_many_snoozed(ids, datetime.fromisoformat(raw_until))
    success = matched == len(ids) if ids else matched > 0
    if action == "read" and isinstance(request.payload.get("tab_key"), str):
        success = matched > 0
    message = (
        f"Applied {action} to {matched} notification(s)"
        if success
        else "one or more notifications are stale or no longer exist"
    )
    return (
        success,
        message,
        {
            "action": action,
            "cancelled_snoozes": bool(request.payload.get("cancelled_snoozes")),
            "description": str(request.payload.get("description") or ""),
            "ids": list(ids),
            "matched_count": matched,
            "muted": _muted_payload(action),
            "snooze_until": snooze_until,
        },
    )


def _muted_payload(action: str) -> bool | None:
    if action == "mute":
        return True
    if action == "unmute":
        return False
    if action == "snooze":
        return True
    return None


__all__ = ["add_notify_operation_parsers", "handle_notify_operation"]
