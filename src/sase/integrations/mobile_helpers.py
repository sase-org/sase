"""Hidden mobile helper bridge operations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from sase.integrations.changespec_tags import list_changespec_xprompt_tags

GATEWAY_WIRE_SCHEMA_VERSION = 1


class _MobileHelperBridgeError(RuntimeError):
    """Deterministic bridge error for invalid mobile helper requests."""


def handle_mobile_helper_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed mobile helper bridge operation over JSON stdin/stdout."""
    try:
        request = _read_request(stdin)
        operation = getattr(args, "mobile_helper_bridge_subcommand", None)
        if operation == "changespec-tags":
            response = _changespec_tags_response(request)
        else:
            raise _MobileHelperBridgeError("unknown mobile helper bridge operation")
    except (_MobileHelperBridgeError, ValueError, TypeError) as exc:
        print(f"mobile helper bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def _read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _MobileHelperBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise _MobileHelperBridgeError("request JSON must be an object")
    return payload


def _changespec_tags_response(request: dict[str, Any]) -> dict[str, Any]:
    project = _optional_string(request.get("project"), "project")
    limit = _optional_limit(request.get("limit"))
    listing = list_changespec_xprompt_tags(project)
    entries = listing.entries
    total_count = len(entries)
    if limit is not None:
        entries = entries[:limit]

    skipped = [_skipped_wire(row) for row in listing.skipped]
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": "partial_success" if skipped else "success",
            "message": _changespec_tags_message(len(entries), len(skipped)),
            "warnings": [],
            "skipped": skipped,
            "partial_failure_count": len(skipped) if skipped else None,
        },
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "tags": [
            {
                "tag": entry.tag,
                "project": entry.project,
                "changespec": entry.name,
                "title": None,
                "status": entry.status,
                "workflow": entry.workflow_type,
                "source_path_display": None,
            }
            for entry in entries
        ],
        "total_count": total_count,
    }


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MobileHelperBridgeError(f"{field} must be a string")
    value = value.strip()
    return value or None


def _optional_limit(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise _MobileHelperBridgeError("limit must be an integer")
    if value < 0:
        raise _MobileHelperBridgeError("limit must be non-negative")
    return value


def _skipped_wire(row: str) -> dict[str, str | None]:
    target, sep, reason = row.partition(": ")
    if not sep:
        return {"target": None, "reason": row}
    return {"target": target, "reason": reason}


def _changespec_tags_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} ChangeSpec tag(s), skipped {skipped_count}"
    return f"loaded {count} ChangeSpec tag(s)"
