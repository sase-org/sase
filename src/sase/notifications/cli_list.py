"""``sase notify list`` — list recent notifications."""

from __future__ import annotations

import argparse
import json
import sys

from sase.notifications.catalog import (
    NotificationInfo,
    list_notification_infos,
    notification_info_to_json,
)

_PRETTY_NOTES_MAX_CHARS = 80


def handle_notify_list(args: argparse.Namespace) -> None:
    """Render the notification catalog (pretty table or JSON)."""
    try:
        infos = list_notification_infos(
            limit=getattr(args, "limit", None),
            query=getattr(args, "query", None),
            sender=getattr(args, "sender", None),
            unread=bool(getattr(args, "unread", False)),
            include_dismissed=bool(getattr(args, "all", False)),
        )
    except Exception as exc:
        print(f"sase notify list: cannot read notifications: {exc}", file=sys.stderr)
        sys.exit(1)

    if bool(getattr(args, "json", False)):
        _print_json(infos)
        return

    _print_pretty(infos)


def _print_json(infos: list[NotificationInfo]) -> None:
    payload = [notification_info_to_json(info) for info in infos]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_pretty(infos: list[NotificationInfo]) -> None:
    title = f"Notifications ({len(infos)})"
    print(title)

    if not infos:
        print("No notifications found.")
        return

    print("ID\tAGE\tSENDER\tSTATE\tNOTES")
    for info in infos:
        print(
            "\t".join(
                [
                    info.id,
                    info.age,
                    info.sender,
                    _state_label(info),
                    _truncate(" | ".join(info.notes), _PRETTY_NOTES_MAX_CHARS),
                ]
            )
        )


def _state_label(info: NotificationInfo) -> str:
    labels: list[str] = []
    if not info.read:
        labels.append("unread")
    if info.priority:
        labels.append("priority")
    if info.dismissed:
        labels.append("dismissed")
    if info.silent:
        labels.append("silent")
    if info.muted:
        labels.append("muted")
    return ",".join(labels) if labels else "-"


def _truncate(text: str, limit: int) -> str:
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 1)] + "..."
