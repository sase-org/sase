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


def handle_notify_operation(args: argparse.Namespace) -> int:
    """Dispatch the notification apply-state command."""
    if getattr(args, "notify_subcommand", None) != "apply-state":
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
        {"action": action, "notification_id": notification_id},
    )


__all__ = ["add_notify_operation_parsers", "handle_notify_operation"]
