"""Handler for the ``sase gate`` CLI command group."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from sase.notification_gates.models import GateError
from sase.notifications.models import normalize_notification_tags


def handle_gate_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch gate subcommands."""
    subcommand = getattr(args, "gate_subcommand", None)
    if subcommand == "create":
        _handle_gate_create(args)
    if subcommand == "wait":
        from sase.notifications.cli_wait import handle_gate_wait

        handle_gate_wait(args)

    print("Usage: sase gate {create,wait}", file=sys.stderr)
    sys.exit(1)


def _handle_gate_create(args: argparse.Namespace) -> NoReturn:
    """Create a durable gate from a JSON specification read from stdin."""
    data = _read_stdin_object()
    sender = getattr(args, "sender", None)
    cli_tags = getattr(args, "tag", None)
    if sender is not None or cli_tags:
        presentation = data.get("presentation", data.get("notification", {}))
        if not isinstance(presentation, dict):
            print("Error: presentation must be an object", file=sys.stderr)
            sys.exit(1)
        presentation = dict(presentation)
        if sender is not None:
            presentation["sender"] = sender
        if cli_tags:
            presentation["tags"] = _create_tags(presentation.get("tags"), cli_tags)
        data["presentation"] = presentation

    try:
        from sase.notification_gates.service import create_gate

        result = create_gate(data)
    except GateError as exc:
        print(f"Error [{exc.code}] {exc.target}: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: gate creation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result.to_dict(), sort_keys=True))
    sys.exit(0)


def _read_stdin_object() -> dict[str, object]:
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: gate specification JSON is required on stdin", file=sys.stderr)
        sys.exit(1)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print("Error: invalid JSON on stdin", file=sys.stderr)
        sys.exit(1)
    if not isinstance(parsed, dict):
        print("Error: stdin JSON must be an object", file=sys.stderr)
        sys.exit(1)
    return parsed


def _create_tags(json_tags: object, cli_tags: list[str]) -> list[str]:
    values: list[str] = []
    if isinstance(json_tags, str):
        values.append(json_tags)
    elif isinstance(json_tags, list):
        values.extend(str(tag) for tag in json_tags)
    elif json_tags is not None:
        values.append(str(json_tags))
    values.extend(cli_tags)
    return normalize_notification_tags(values)


__all__ = ["handle_gate_command"]
