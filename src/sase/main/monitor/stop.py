"""Stop handler for ``sase monitor``."""

from __future__ import annotations

import argparse
import json
import sys

from sase.monitor import MonitorRefError, short_monitor_id, stop_monitor

from ..monitor_render import monitor_stop_json
from .common import resolve_ref_or_active


def handle_monitor_stop(args: argparse.Namespace) -> int:
    """Stop one running monitor, resolving the same refs as ``monitor show``."""
    from sase.ops.commands.monitor import emit_monitor_stop_result

    try:
        record = resolve_ref_or_active(getattr(args, "monitor_id", None))
    except MonitorRefError as exc:
        message = f"sase monitor stop: {exc}"
        emit_monitor_stop_result(
            success=False,
            message=message,
            payload={},
        )
        print(message, file=sys.stderr)
        return 2

    was_active = record.monitor_state == "running"
    result = stop_monitor(record)
    changed = was_active and result.monitor_state != "running"
    short_id = short_monitor_id(result.monitor_id)
    message = (
        f"Stopped monitor {short_id}."
        if changed
        else f"Monitor {short_id} is already {result.monitor_state}; nothing to do."
    )
    emit_monitor_stop_result(
        success=True,
        message=message,
        payload={
            "changed": changed,
            "monitor_id": result.monitor_id,
            "state": result.monitor_state,
        },
    )

    if bool(getattr(args, "json", False)):
        json.dump(monitor_stop_json(result, changed=changed), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(message)
    if changed and result.next_action:
        print("No follow-up agent was launched (stopped, not finished).")
    return 0


__all__ = [
    "handle_monitor_stop",
]
