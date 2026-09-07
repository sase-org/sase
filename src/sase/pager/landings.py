"""Pager documents for commits, binary cards, and ambiguous source paths."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_cli.references import ResolvedArtifactReference
from sase.artifact_ref_models import ArtifactRefTargetResolution
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkResolutionContext
from sase.pager.owner import document_owner_from_path, inherit_owner_context
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind
from sase.pager.source_resolve import (
    owned_source_candidate_paths,
    owned_source_unresolved_message,
)


def commit_link_target(
    result: ResolvedArtifactReference,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget:
    """Build a commit/stitch landing with identifiable metadata, not a self-card."""
    properties: dict[str, str] = {}
    if result.entry is not None:
        properties = dict(result.entry.properties)
    sha = properties.get("sha") or result.parsed.payload.sha or "-"
    lines = [
        f"kind: {result.parsed.kind}",
        f"reference: {result.canonical_reference}",
        f"status: {result.resolution.status}",
        f"locator: {result.resolution.locator or '-'}",
        f"subject: {properties.get('subject') or '-'}",
        f"author: {properties.get('author') or '-'}",
        f"repo: {properties.get('repo') or '-'}",
        f"sha: {sha}",
    ]
    authored_at = properties.get("authored_at")
    if authored_at:
        lines.append(f"authored_at: {authored_at}")
    body = "\n".join(lines) + "\n"
    path = result.resolution.resolved_path
    owner = (
        None
        if path is None
        else document_owner_from_path(path, source_reference=result.canonical_reference)
    )
    document = PagerDocument(
        sections=(
            PagerSection(
                identity=result.canonical_reference,
                title=result.canonical_reference,
                kind="commit",
                body=body,
                subject_ref=result.canonical_reference,
                origin=PagerOrigin.DIFF,
                owner=owner,
            ),
        ),
        title=result.canonical_reference,
        origin=PagerOrigin.DIFF,
        link_context=(
            inherit_owner_context(path, context) if path is not None else context
        ),
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def ambiguous_source_resolution(
    path_text: str,
    resolution: ArtifactRefTargetResolution,
    context: LinkResolutionContext,
) -> LinkResolution:
    """Return followable candidate paths, or copy explaining the ambiguity."""
    paths = owned_source_candidate_paths(resolution)
    message = owned_source_unresolved_message(path_text, resolution)
    if not paths:
        return LinkResolution(unresolved_message=message)
    body = "\n".join(str(path) for path in paths) + "\n"
    document = PagerDocument(
        sections=(
            PagerSection(
                identity=f"ambiguous:{path_text}",
                title=path_text,
                kind="file",
                body=body,
                subject_ref=path_text,
                owner=context.owner,
            ),
        ),
        title=f"ambiguous · {path_text}",
        origin=PagerOrigin.FILE,
        link_context=context,
    )
    return LinkResolution(
        target=LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document)
    )


def card_link_target(
    result: ResolvedArtifactReference,
    *,
    path: Path | None,
    context: LinkResolutionContext | None = None,
) -> LinkTarget:
    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime = result.file.mime_type if result.file is not None else None
    document = binary_card_document(
        result.canonical_reference,
        path=path,
        mime=mime,
        kind=kind,
        status=result.resolution.status,
        context=context,
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def binary_card_document(
    title: str,
    *,
    path: Path | None,
    mime: str | None,
    kind: str | None = None,
    status: str | None = None,
    context: LinkResolutionContext | None = None,
) -> PagerDocument:
    lines = []
    if kind is not None:
        lines.append(f"kind: {kind}")
    lines.append(f"reference: {title}")
    if status is not None:
        lines.append(f"status: {status}")
    lines.append(f"mime_type: {mime or '-'}")
    lines.append(f"path: {path if path is not None else '-'}")
    body = "\n".join(lines) + "\n"
    return PagerDocument(
        sections=(PagerSection(identity=title, title=title, kind="file", body=body),),
        title=title,
        origin=PagerOrigin.FILE,
        link_context=(
            inherit_owner_context(path, context) if path is not None else context
        ),
    )


__all__ = [
    "ambiguous_source_resolution",
    "binary_card_document",
    "card_link_target",
    "commit_link_target",
]
