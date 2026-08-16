"""Shared field extraction for generic document-provider archive rows."""

from __future__ import annotations

from pathlib import Path

from .plans_data_models import ProjectArchive


def provider_document_field_value(entry: ProjectArchive, field: str) -> str:
    """Return a display/query value for a declared provider field."""

    plan = entry.match.plan
    frontmatter = plan.frontmatter
    if field == "title":
        return plan.title or plan.name
    if field == "filename":
        return Path(plan.path).name
    if field == "path":
        return plan.path
    if field == "relpath":
        return plan.relpath
    if field == "project":
        return entry.project
    if field == "created_at":
        return plan.created_at or frontmatter.get("create_time", "")
    if field == "updated_at":
        return frontmatter.get("updated_time", "") or frontmatter.get("updated_at", "")
    if field == "status":
        return plan.status or frontmatter.get("status", "")
    if field == "kind":
        return entry.role or plan.kind
    return frontmatter.get(field, "")


def provider_document_field_values(
    entry: ProjectArchive, field: str
) -> tuple[str, ...]:
    """Return a normalized tuple for repeatable/filterable presentation fields."""

    value = provider_document_field_value(entry, field)
    if not value:
        return ()
    if "," not in value:
        return (value,)
    return tuple(item.strip() for item in value.split(",") if item.strip())


__all__ = ["provider_document_field_value", "provider_document_field_values"]
