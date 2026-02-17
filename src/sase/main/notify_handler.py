"""Handler for the 'sase notify' CLI subcommand."""

import argparse
import json
import sys
import uuid
from datetime import datetime
from typing import NoReturn

from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from sase.sase_utils import EASTERN_TZ


def handle_notify_command(args: argparse.Namespace) -> NoReturn:
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
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender=data["sender"],
        notes=data.get("notes", []),
        files=data.get("files", []),
        action=data.get("action"),
        action_data=data.get("action_data", {}),
    )

    append_notification(notification)
    print(notification.id)
    sys.exit(0)
