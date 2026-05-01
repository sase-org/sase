"""``sase notify show`` — print one notification by id."""

from __future__ import annotations

import argparse
import json
import sys

from sase.notifications.catalog import (
    NotificationInfo,
    notification_info_to_json,
    resolve_notification_ref,
)


def handle_notify_show(args: argparse.Namespace) -> None:
    """Resolve a notification id and print the requested format."""
    notification_id: str = args.id
    fmt: str = args.format or "markdown"

    try:
        info = resolve_notification_ref(notification_id)
    except Exception as exc:
        print(f"sase notify show: cannot read notifications: {exc}", file=sys.stderr)
        sys.exit(1)

    if info is None:
        print(
            f"sase notify show: notification not found: {notification_id}",
            file=sys.stderr,
        )
        sys.exit(2)

    if fmt == "json":
        _print_json(info)
        return
    if fmt == "markdown":
        _print_markdown(info)
        return

    print(f"sase notify show: unknown format: {fmt}", file=sys.stderr)
    sys.exit(2)


def _print_json(info: NotificationInfo) -> None:
    json.dump(notification_info_to_json(info), sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_markdown(info: NotificationInfo) -> None:
    sys.stdout.write(f"# Notification {info.id}\n\n")
    sys.stdout.write(f"- id: `{info.id}`\n")
    sys.stdout.write(f"- timestamp: `{info.timestamp}` ({info.age})\n")
    sys.stdout.write(f"- sender: `{info.sender}`\n")
    sys.stdout.write(f"- priority: {_bool_text(info.priority)}\n")
    sys.stdout.write("- notes:\n")
    if info.notes:
        for note in info.notes:
            sys.stdout.write(f"  - {note}\n")
    else:
        sys.stdout.write("  - none\n")
    sys.stdout.write("- files:\n")
    if info.files:
        for path in info.files:
            sys.stdout.write(f"  - `{path}`\n")
    else:
        sys.stdout.write("  - none\n")
    sys.stdout.write(
        f"- action: `{info.action}`\n" if info.action else "- action: none\n"
    )
    sys.stdout.write("- action_data:\n")
    if info.action_data:
        for key, data_value in info.action_data.items():
            sys.stdout.write(f"  - {key}: `{data_value}`\n")
    else:
        sys.stdout.write("  - none\n")
    sys.stdout.write("- state:\n")
    state_rows: list[tuple[str, bool]] = [
        ("read", info.read),
        ("dismissed", info.dismissed),
        ("silent", info.silent),
        ("muted", info.muted),
    ]
    for key, state_value in state_rows:
        sys.stdout.write(f"  - {key}: {_bool_text(state_value)}\n")
    if info.snooze_until:
        sys.stdout.write(f"  - snooze_until: `{info.snooze_until}`\n")
    else:
        sys.stdout.write("  - snooze_until: none\n")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
