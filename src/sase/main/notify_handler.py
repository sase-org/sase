"""Handler for the 'sase notify' CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from typing import NoReturn

from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from sase.core.time import get_timezone


def handle_notify_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch notification subcommands or preserve legacy creation."""
    subcommand = getattr(args, "notify_subcommand", None)
    if subcommand in (None, "create"):
        _handle_notify_create(args)
    if subcommand == "list":
        from sase.notifications.cli_list import handle_notify_list

        handle_notify_list(args)
        sys.exit(0)
    if subcommand == "show":
        from sase.notifications.cli_show import handle_notify_show

        handle_notify_show(args)
        sys.exit(0)

    print("Usage: sase notify [create|list|show]", file=sys.stderr)
    sys.exit(1)


def _handle_notify_create(args: argparse.Namespace) -> NoReturn:
    """Create a notification from stdin JSON and/or CLI flags."""
    data: dict = {}

    # Read JSON from stdin if not a tty
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("Error: invalid JSON on stdin", file=sys.stderr)
                sys.exit(1)

    # --sender flag overrides JSON sender
    if args.sender is not None:
        data["sender"] = args.sender

    if not data.get("sender"):
        print("Error: sender is required (via JSON or --sender)", file=sys.stderr)
        sys.exit(1)

    notification = Notification(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=data["sender"],
        notes=data.get("notes", []),
        files=data.get("files", []),
        action=data.get("action"),
        action_data=data.get("action_data", {}),
    )

    append_notification(notification)
    print(notification.id)
    sys.exit(0)
