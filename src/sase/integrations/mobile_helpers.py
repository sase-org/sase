"""Hidden mobile helper bridge operations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from sase.integrations.changespec_tags import list_changespec_xprompt_tags
from sase.xprompt.catalog import build_structured_xprompts_catalog

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
        elif operation == "xprompt-catalog":
            response = _xprompt_catalog_response(request)
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


def _xprompt_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    project = _optional_string(request.get("project"), "project")
    source = _optional_string(request.get("source"), "source")
    tag = _optional_string(request.get("tag"), "tag")
    query = _optional_string(request.get("query"), "query")
    include_pdf = _optional_bool(request.get("include_pdf"), "include_pdf")
    limit = _optional_limit(request.get("limit"))
    projection = build_structured_xprompts_catalog(
        project=project,
        source=source,
        tag=tag,
        query=query,
        include_pdf=include_pdf,
        limit=limit,
    )
    skipped = [
        {"target": row.target, "reason": row.reason} for row in projection.skipped
    ]
    status = "partial_success" if skipped else "success"
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": status,
            "message": _xprompt_catalog_message(len(projection.entries), len(skipped)),
            "warnings": projection.warnings,
            "skipped": skipped,
            "partial_failure_count": len(skipped) if skipped else None,
        },
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "entries": [
            {
                "name": entry.name,
                "display_label": entry.display_label,
                "description": entry.description,
                "source_bucket": entry.source_bucket,
                "project": entry.project,
                "tags": entry.tags,
                "input_signature": entry.input_signature,
                "is_skill": entry.is_skill,
                "content_preview": entry.content_preview,
                "source_path_display": entry.source_path_display,
            }
            for entry in projection.entries
        ],
        "stats": {
            "total_count": projection.stats.total_count,
            "project_count": projection.stats.project_count,
            "skill_count": projection.stats.skill_count,
            "pdf_requested": projection.stats.pdf_requested,
        },
        "catalog_attachment": None
        if projection.catalog_attachment is None
        else {
            "display_name": projection.catalog_attachment.display_name,
            "content_type": projection.catalog_attachment.content_type,
            "byte_size": projection.catalog_attachment.byte_size,
            "path_display": projection.catalog_attachment.path_display,
            "generated": projection.catalog_attachment.generated,
        },
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


def _optional_bool(value: object, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _MobileHelperBridgeError(f"{field} must be a boolean")
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


def _xprompt_catalog_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} xprompt(s), skipped {skipped_count}"
    return f"loaded {count} xprompt(s)"
