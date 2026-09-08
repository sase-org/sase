"""``sase notify +1`` — append a corroboration note to an existing notification."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime
from typing import NoReturn

from sase.agent.identity import discover_agent_identity
from sase.core.time import get_timezone
from sase.notifications.catalog import resolve_notification_id_prefix
from sase.notifications.store import append_notification_plus_one


def _resolve_notify_sender(explicit: str | None) -> str:
    """Resolve the acting sender: an explicit override, else agent/user identity."""
    if explicit:
        return explicit
    identity = discover_agent_identity()
    if identity is not None:
        return identity.name
    return getpass.getuser()


def handle_notify_plus_one(args: argparse.Namespace) -> NoReturn:
    """Append one +1 by notification id/prefix or by ``(sender, dedup_key)``."""
    dedup_key: str | None = getattr(args, "dedup_key", None)
    notification_id: str | None = getattr(args, "id", None)

    if not dedup_key and not notification_id:
        print(
            "Error: an id (or unique prefix) or -k/--dedup-key is required",
            file=sys.stderr,
        )
        sys.exit(1)
    if dedup_key and notification_id:
        print("Error: pass an id or -k/--dedup-key, not both", file=sys.stderr)
        sys.exit(1)

    sender = _resolve_notify_sender(getattr(args, "sender", None))
    timestamp = datetime.now(get_timezone()).isoformat()

    if dedup_key:
        outcome = append_notification_plus_one(
            note=args.note,
            sender=sender,
            timestamp=timestamp,
            dedup_key=dedup_key,
        )
        if outcome.action == "no_match":
            print(json.dumps({"action": "no_match"}))
            sys.exit(0)
        print(json.dumps({"action": outcome.action, "id": outcome.id}))
        sys.exit(0)

    resolved_id = resolve_notification_id_prefix(str(notification_id))
    if resolved_id is None:
        print(f"Error: notification not found: {notification_id}", file=sys.stderr)
        sys.exit(1)

    outcome = append_notification_plus_one(
        note=args.note,
        sender=sender,
        timestamp=timestamp,
        notification_id=resolved_id,
    )
    if outcome.action == "no_match":
        print(f"Error: notification not found: {notification_id}", file=sys.stderr)
        sys.exit(1)
    print(outcome.id)
    sys.exit(0)
