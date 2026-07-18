"""Handler for the 'sase notify' CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from typing import NoReturn

from sase.core.time import get_timezone
from sase.notification_gates.models import GateError, validate_icon
from sase.notification_gates.registry import PRIVILEGED_GATE_ACTIONS
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import append_notification


def handle_notify_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch notification subcommands."""
    subcommand = getattr(args, "notify_subcommand", None)
    if subcommand == "create":
        _handle_notify_create(args)
    if subcommand in (None, "list"):
        from sase.notifications.cli_list import handle_notify_list

        handle_notify_list(args)
        sys.exit(0)
    if subcommand == "show":
        from sase.notifications.cli_show import handle_notify_show

        handle_notify_show(args)
        sys.exit(0)
    print("Usage: sase notify {create,list,show}", file=sys.stderr)
    sys.exit(1)


def _handle_notify_create(args: argparse.Namespace) -> NoReturn:
    """Create a notification from stdin JSON and/or CLI flags."""
    data: dict[str, object] = {}

    # Read JSON from stdin if not a tty
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                print("Error: invalid JSON on stdin", file=sys.stderr)
                sys.exit(1)
            if not isinstance(parsed, dict):
                print("Error: stdin JSON must be an object", file=sys.stderr)
                sys.exit(1)
            data = parsed

    # --sender flag overrides JSON sender
    if args.sender is not None:
        data["sender"] = args.sender

    if not data.get("sender"):
        print("Error: sender is required (via JSON or --sender)", file=sys.stderr)
        sys.exit(1)

    try:
        icon = validate_icon(data.get("icon"), "icon")
    except GateError as exc:
        print(f"Error [{exc.code}] {exc.target}: {exc}", file=sys.stderr)
        sys.exit(1)

    notification = Notification(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=str(data["sender"]),
        icon=icon,
        notes=_create_string_list(data.get("notes")),
        files=_create_string_list(data.get("files")),
        tags=_create_tags(data.get("tags"), getattr(args, "tag", None)),
        action=None if data.get("action") is None else str(data["action"]),
        action_data=_create_action_data(data.get("action_data")),
        silent=bool(data.get("silent", False)),
    )

    if notification.action in PRIVILEGED_GATE_ACTIONS:
        print(
            f"Error: {notification.action} is privileged; use sase gate create",
            file=sys.stderr,
        )
        sys.exit(1)

    append_notification(notification)
    print(notification.id)
    sys.exit(0)


def _create_tags(json_tags: object, cli_tags: list[str] | None) -> list[str]:
    values: list[str] = []
    if isinstance(json_tags, str):
        values.append(json_tags)
    elif isinstance(json_tags, list):
        values.extend(str(tag) for tag in json_tags)
    elif json_tags is not None:
        values.append(str(json_tags))
    values.extend(cli_tags or [])
    return normalize_notification_tags(values)


def _create_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _create_action_data(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
