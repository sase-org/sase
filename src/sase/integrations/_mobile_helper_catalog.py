"""Mobile helper bridge operations for ChangeSpec tags and xprompt catalog."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.daemon.client import LocalDaemonTransportError
from sase.daemon.read_facade import read_or_fallback
from sase.integrations.changespec_tags import list_changespec_xprompt_tags
from sase.xprompt.catalog import build_structured_xprompts_catalog

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    optional_bool,
    optional_limit,
    optional_string,
)


def changespec_tags_response(request: dict[str, Any]) -> dict[str, Any]:
    project = optional_string(request.get("project"), "project")
    limit = optional_limit(request.get("limit"))
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


def xprompt_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    project = optional_string(request.get("project"), "project")
    source = optional_string(request.get("source"), "source")
    tag = optional_string(request.get("tag"), "tag")
    query = optional_string(request.get("query"), "query")
    include_pdf = optional_bool(request.get("include_pdf"), "include_pdf")
    limit = optional_limit(request.get("limit"))
    no_daemon = optional_bool(request.get("no_daemon"), "no_daemon")
    if _can_route_xprompt_catalog(project, source, tag, include_pdf):
        result = read_or_fallback(
            "xprompt_catalog",
            args=SimpleNamespace(no_daemon=no_daemon),
            direct_loader=lambda: _direct_xprompt_catalog_response(
                project=project,
                source=source,
                tag=tag,
                query=query,
                include_pdf=include_pdf,
                limit=limit,
            ),
            daemon_loader=lambda daemon: _daemon_xprompt_catalog_response(
                daemon, project=project, query=query, limit=limit
            ),
        )
        return result.value

    return _direct_xprompt_catalog_response(
        project=project,
        source=source,
        tag=tag,
        query=query,
        include_pdf=include_pdf,
        limit=limit,
    )


def _direct_xprompt_catalog_response(
    *,
    project: str | None,
    source: str | None,
    tag: str | None,
    query: str | None,
    include_pdf: bool,
    limit: int | None,
) -> dict[str, Any]:
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
                "insertion": entry.insertion,
                "reference_prefix": entry.reference_prefix,
                "kind": entry.kind,
                "description": entry.description,
                "source_bucket": entry.source_bucket,
                "project": entry.project,
                "tags": entry.tags,
                "input_signature": entry.input_signature,
                "inputs": [
                    {
                        "name": inp.name,
                        "type": inp.type,
                        "required": inp.required,
                        "default_display": inp.default_display,
                        "position": inp.position,
                    }
                    for inp in entry.inputs
                ],
                "is_skill": entry.is_skill,
                "content_preview": entry.content_preview,
                "source_path_display": entry.source_path_display,
                "definition_path": entry.definition_path,
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


def _can_route_xprompt_catalog(
    project: str | None,
    source: str | None,
    tag: str | None,
    include_pdf: bool,
) -> bool:
    return project is not None and source is None and tag is None and not include_pdf


def _daemon_xprompt_catalog_response(
    daemon: Any,
    *,
    project: str | None,
    query: str | None,
    limit: int | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    skipped: list[dict[str, str | None]] = []
    cursor: str | None = None
    while True:
        raw = daemon.xprompt_catalog(
            project_id=project,
            query=query,
            limit=500,
            cursor=cursor,
        )
        entries.extend(_xprompt_entries_from_daemon(raw))
        warnings.extend(_catalog_warning_strings(raw))
        skipped.extend(_catalog_skipped_rows(raw))
        page = raw.get("page")
        cursor = page.get("next_cursor") if isinstance(page, dict) else None
        if not isinstance(cursor, str) or not cursor:
            break

    total_count = len(entries)
    if limit is not None:
        entries = entries[:limit]
    skipped_count = len(skipped)
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": "partial_success" if skipped else "success",
            "message": _xprompt_catalog_message(len(entries), skipped_count),
            "warnings": warnings,
            "skipped": skipped,
            "partial_failure_count": skipped_count if skipped else None,
        },
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "entries": entries,
        "stats": {
            "total_count": total_count,
            "project_count": sum(
                1 for entry in entries if entry.get("source_bucket") == "project"
            ),
            "skill_count": sum(1 for entry in entries if entry.get("is_skill")),
            "pdf_requested": False,
        },
        "catalog_attachment": None,
    }


def _xprompt_entries_from_daemon(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw.get("entries")
    if isinstance(rows, list):
        return [_require_entry(row) for row in rows]

    projected = raw.get("xprompts")
    if isinstance(projected, list):
        entries: list[dict[str, Any]] = []
        for row in projected:
            if not isinstance(row, dict):
                raise _daemon_payload_error("xprompt catalog row is not an object")
            entry = row.get("entry")
            entries.append(_require_entry(entry))
        return entries
    raise _daemon_payload_error("xprompt catalog payload did not include entries")


def _require_entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _daemon_payload_error("xprompt catalog entry is not an object")
    return {
        "name": value.get("name"),
        "display_label": value.get("display_label"),
        "insertion": value.get("insertion"),
        "reference_prefix": value.get("reference_prefix"),
        "kind": value.get("kind"),
        "description": value.get("description"),
        "source_bucket": value.get("source_bucket"),
        "project": value.get("project"),
        "tags": list(value.get("tags") or []),
        "input_signature": value.get("input_signature"),
        "inputs": list(value.get("inputs") or []),
        "is_skill": bool(value.get("is_skill", False)),
        "content_preview": value.get("content_preview"),
        "source_path_display": value.get("source_path_display"),
        "definition_path": value.get("definition_path"),
    }


def _catalog_warning_strings(raw: dict[str, Any]) -> list[str]:
    warnings = raw.get("warnings")
    result = (
        [row for row in warnings if isinstance(row, str)]
        if isinstance(warnings, list)
        else []
    )
    if raw.get("resync_required") is True:
        result.append("daemon catalog resync required")
    return result


def _catalog_skipped_rows(raw: dict[str, Any]) -> list[dict[str, str | None]]:
    rows = raw.get("skipped")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, str | None]] = []
    for row in rows:
        if isinstance(row, dict):
            target = row.get("target")
            reason = row.get("reason")
            result.append(
                {
                    "target": target if isinstance(target, str) else None,
                    "reason": reason if isinstance(reason, str) else None,
                }
            )
    return result


def _daemon_payload_error(message: str) -> LocalDaemonTransportError:
    return LocalDaemonTransportError(
        message,
        code="projection_degraded",
        fallback_reason="unsupported_daemon_payload",
    )


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
