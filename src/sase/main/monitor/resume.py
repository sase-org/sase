"""Resume handler for ``sase monitor``."""

from __future__ import annotations

import argparse
import json
import sys

from sase.monitor import MonitorRefError, MonitorResumeError, resume_monitor

from .common import optional_text, resolve_ref


def handle_monitor_resume(args: argparse.Namespace) -> int:
    """Resume a terminal monitor's requested ordinary continuation."""

    try:
        record = resolve_ref(getattr(args, "monitor_id", ""))
    except MonitorRefError as exc:
        return _emit_resume_error(args, f"sase monitor resume: {exc}", code="ref")

    try:
        result = resume_monitor(
            record,
            checkpoint_path=optional_text(getattr(args, "checkpoint", None)),
            model=optional_text(getattr(args, "model", None)),
        )
    except MonitorResumeError as exc:
        return _emit_resume_error(
            args,
            f"sase monitor resume: {exc}",
            code=exc.code,
            suggested_command=exc.suggested_command,
        )
    except ValueError as exc:
        return _emit_resume_error(args, f"sase monitor resume: {exc}", code="invalid")

    payload = {
        "success": True,
        "monitor_id": result.monitor_id,
        "branch": result.branch,
        "agent_name": result.agent_name,
        "delivery_disposition": result.delivery_disposition,
        "launched": result.launched,
        "spawned": result.spawned,
        "manual_revision": result.manual_revision,
        "reused_revision": result.reused_revision,
        "ownership_outcome": result.ownership_outcome,
        "message": result.message,
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(result.message)
    if result.agent_name:
        print(f"  member: {result.agent_name}")
    print(f"  branch: {result.branch}")
    if result.delivery_disposition:
        print(f"  delivery: {result.delivery_disposition}")
    return 0


def _emit_resume_error(
    args: argparse.Namespace,
    message: str,
    *,
    code: str,
    suggested_command: str | None = None,
) -> int:
    if bool(getattr(args, "json", False)):
        payload = {
            "success": False,
            "error": message.removeprefix("sase monitor resume: "),
            "code": code,
            "suggested_command": suggested_command,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(message, file=sys.stderr)
        if suggested_command:
            print(f"eligible resume command: {suggested_command}", file=sys.stderr)
    return 2


__all__ = [
    "handle_monitor_resume",
]
