"""Mobile-safe structured xprompt catalog projection."""

from __future__ import annotations

from ._catalog_format import MAX_MOBILE_CONTENT_PREVIEW_CHARS, format_inputs
from ._catalog_models import (
    StructuredCatalogAttachment,
    StructuredCatalogEntry,
    StructuredCatalogInput,
    StructuredCatalogProjection,
    StructuredCatalogSkipped,
    StructuredCatalogSource,
    StructuredCatalogStats,
    NoXpromptsFound,
    PdfEngineUnavailable,
)
from ._catalog_render import build_xprompts_catalog
from ._catalog_sources import (
    gather_structured_entries,
    safe_file_size,
    safe_path_display,
    source_path_display,
)
from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.reference_display import (
    workflow_kind_value,
    workflow_reference_insertion,
    workflow_reference_prefix,
)


def build_structured_xprompts_catalog(
    *,
    project: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    include_pdf: bool = False,
    limit: int | None = None,
) -> StructuredCatalogProjection:
    """Return a mobile-safe structured xprompt catalog projection.

    This path intentionally gathers and filters xprompt metadata without
    requiring an HTML/PDF renderer. PDF generation is best-effort and only runs
    when explicitly requested.
    """
    filtered_entries = filter_structured_catalog_entries(
        gather_structured_entries(),
        project=project,
        source=source,
        tag=tag,
        query=query,
    )
    total_count = len(filtered_entries)
    entries = filtered_entries
    if limit is not None:
        entries = entries[:limit]

    structured_entries = [structured_entry(entry) for entry in entries]
    warnings: list[str] = []
    skipped: list[StructuredCatalogSkipped] = []
    attachment: StructuredCatalogAttachment | None = None

    if include_pdf:
        try:
            artifact = build_xprompts_catalog()
        except NoXpromptsFound as exc:
            warnings.append("PDF catalog was not generated")
            skipped.append(
                StructuredCatalogSkipped(target="xprompt-catalog.pdf", reason=str(exc))
            )
        except PdfEngineUnavailable as exc:
            warnings.append("PDF catalog was not generated")
            skipped.append(
                StructuredCatalogSkipped(target="xprompt-catalog.pdf", reason=str(exc))
            )
        else:
            attachment = StructuredCatalogAttachment(
                display_name=artifact.pdf_path.name,
                content_type="application/pdf",
                byte_size=safe_file_size(artifact.pdf_path),
                path_display=safe_path_display(artifact.pdf_path),
                generated=True,
            )

    return StructuredCatalogProjection(
        entries=structured_entries,
        stats=StructuredCatalogStats(
            total_count=total_count,
            project_count=len(
                {entry.project for entry in filtered_entries if entry.project}
            ),
            skill_count=sum(1 for entry in filtered_entries if entry.is_skill),
            pdf_requested=include_pdf,
        ),
        warnings=warnings,
        skipped=skipped,
        catalog_attachment=attachment,
    )


def filter_structured_catalog_entries(
    entries: list[StructuredCatalogSource],
    *,
    project: str | None,
    source: str | None,
    tag: str | None,
    query: str | None,
) -> list[StructuredCatalogSource]:
    normalized_query = query.casefold() if query else None
    filtered: list[StructuredCatalogSource] = []
    for entry in entries:
        if project is not None and entry.project not in (None, project):
            continue
        if source is not None and entry.bucket != source:
            continue
        tag_values = [tag.value for tag in entry.workflow.tags]
        if tag is not None and tag not in tag_values:
            continue
        if normalized_query is not None and not structured_entry_matches_query(
            entry, tag_values, normalized_query
        ):
            continue
        filtered.append(entry)
    return filtered


def structured_entry_matches_query(
    entry: StructuredCatalogSource, tag_values: list[str], query: str
) -> bool:
    haystack = "\n".join(
        part
        for part in (
            entry.name,
            entry.description or "",
            entry.content,
            " ".join(tag_values),
        )
        if part
    )
    return query in haystack.casefold()


def structured_entry(entry: StructuredCatalogSource) -> StructuredCatalogEntry:
    input_signature = format_inputs(entry.workflow.inputs) or None
    return StructuredCatalogEntry(
        name=entry.name,
        display_label=display_label(entry.name),
        insertion=workflow_reference_insertion(entry.name, entry.workflow),
        reference_prefix=workflow_reference_prefix(entry.workflow),
        kind=workflow_kind_value(entry.workflow),
        description=entry.description,
        source_bucket=entry.bucket,
        project=entry.project,
        tags=sorted(tag.value for tag in entry.workflow.tags),
        input_signature=input_signature,
        inputs=structured_inputs(entry.workflow.inputs),
        is_skill=entry.is_skill,
        content_preview=content_preview(entry.content),
        source_path_display=source_path_display(entry),
    )


def structured_inputs(inputs: list[InputArg]) -> list[StructuredCatalogInput]:
    rows: list[StructuredCatalogInput] = []
    for inp in inputs:
        if inp.is_step_input:
            continue
        rows.append(
            StructuredCatalogInput(
                name=inp.name,
                type=inp.type.value,
                required=inp.default is UNSET,
                default_display=default_display(inp.default),
                position=len(rows),
            )
        )
    return rows


def default_display(default: object) -> str | None:
    if default is UNSET or default is None or isinstance(default, str):
        return None
    if isinstance(default, bool):
        return "true" if default else "false"
    if isinstance(default, (int, float)):
        return str(default)
    return None


def display_label(name: str) -> str:
    label = name.replace("_", " ").replace("-", " ").strip()
    return label or name


def content_preview(content: str) -> str | None:
    text = content.strip()
    if not text:
        return None
    if len(text) <= MAX_MOBILE_CONTENT_PREVIEW_CHARS:
        return text
    return text[:MAX_MOBILE_CONTENT_PREVIEW_CHARS].rstrip() + "..."


_filter_structured_catalog_entries = filter_structured_catalog_entries
_structured_entry_matches_query = structured_entry_matches_query
_structured_entry = structured_entry
_structured_inputs = structured_inputs
_default_display = default_display
_display_label = display_label
_content_preview = content_preview
