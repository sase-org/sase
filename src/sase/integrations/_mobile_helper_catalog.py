"""Mobile helper bridge operations for ChangeSpec tags and xprompt catalog."""

from __future__ import annotations

from typing import Any

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
