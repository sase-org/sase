"""Mobile helper bridge operations for Patch tags and xprompt catalog."""

from __future__ import annotations

from typing import Any

from sase.integrations.changespec_tags import list_patch_xprompt_tags
from sase.xprompt.loader import inactive_project_message_for_ref
from sase.xprompt.catalog import build_structured_xprompts_catalog
from sase.project_display_names import project_display_name_for

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    optional_bool,
    optional_limit,
    optional_string,
)


def patch_tags_response(request: dict[str, Any]) -> dict[str, Any]:
    project = optional_string(request.get("project"), "project")
    limit = optional_limit(request.get("limit"))
    listing = list_patch_xprompt_tags(project)
    entries = listing.entries
    total_count = len(entries)
    if limit is not None:
        entries = entries[:limit]

    skipped = [_skipped_wire(row) for row in listing.skipped]
    warnings: list[str] = []
    inactive_message = (
        inactive_project_message_for_ref(project) if project is not None else None
    )
    if inactive_message is not None:
        warnings.append(inactive_message)
        skipped.append({"target": project, "reason": inactive_message})
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": "partial_success" if skipped else "success",
            "message": _patch_tags_message(len(entries), len(skipped)),
            "warnings": warnings,
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
                "project": project_display_name_for(entry.project),
                "patch": entry.name,
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
    warnings = list(projection.warnings)
    inactive_message = (
        inactive_project_message_for_ref(project) if project is not None else None
    )
    if inactive_message is not None:
        warnings.append(inactive_message)
        skipped.append({"target": project, "reason": inactive_message})
    status = "partial_success" if skipped else "success"
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": status,
            "message": _xprompt_catalog_message(len(projection.entries), len(skipped)),
            "warnings": warnings,
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
                "memory_type": entry.memory_type,
                "ref_kind": entry.ref_kind,
                "ref_sidecar_role": entry.ref_sidecar_role,
                "ref_path_globs": (
                    list(entry.ref_path_globs)
                    if entry.ref_path_globs is not None
                    else None
                ),
                "ref_shadowed_sources": list(entry.ref_shadowed_sources),
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
                        "repeatable": inp.repeatable,
                        "description": inp.description,
                    }
                    for inp in entry.inputs
                ],
                "is_skill": entry.is_skill,
                "skill_name": entry.skill_name,
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
            "memory_count": projection.stats.memory_count,
            "ref_count": projection.stats.ref_count,
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


def _patch_tags_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} Patch tag(s), skipped {skipped_count}"
    return f"loaded {count} Patch tag(s)"


def _xprompt_catalog_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} xprompt(s), skipped {skipped_count}"
    return f"loaded {count} xprompt(s)"
