"""``sase agent hijack`` — stop a stalled agent but keep its work.

Synchronous: exit 0 means the agent is HIJACKED with its workspace claim
held, 2 means refused with nothing changed, and 1 means the stop failed or
an error occurred. ``-j`` emits one stable JSON envelope.
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.text import Text

from sase.agent.hijack.stop import HijackStopResult, stop_agent_for_hijack

HIJACK_JSON_SCHEMA_VERSION = 1


def handle_agents_hijack(args: argparse.Namespace) -> int:
    """Hijack the named agent, echoing the outcome."""
    name: str = args.name
    reason = getattr(args, "reason", None)
    as_json = bool(getattr(args, "json", False))
    result: HijackStopResult = stop_agent_for_hijack(
        name, reason=reason if isinstance(reason, str) else None
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": HIJACK_JSON_SCHEMA_VERSION,
                    "ok": result.exit_code == 0,
                    "name": name,
                    "status": result.status,
                    "hijack_id": result.hijack_id,
                    "workspace_num": (result.record or {}).get("workspace_num"),
                    "message": result.message,
                    "reason": result.reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return result.exit_code
    if result.exit_code == 0:
        Console().print(Text(result.message, style="bold #FF5FAF"))
        return 0
    if result.exit_code == 2:
        print(result.message, file=sys.stderr)
        return 2
    Console(stderr=True).print(Text(result.message, style="bold red"))
    return 1


__all__ = ["HIJACK_JSON_SCHEMA_VERSION", "handle_agents_hijack"]
