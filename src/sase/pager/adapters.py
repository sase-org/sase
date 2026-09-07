"""Adapters that build pager documents from existing SASE inputs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.core.source_language_facade import logical_source_filename
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import (
    LinkResolutionContext,
    default_link_context,
    link_anchor_for_directory,
)
from sase.pager.owner import document_owner_from_path
from sase.pager.syntax_policy import classify_source


def document_from_paths(
    paths: Sequence[str | Path],
    *,
    cwd: str | Path | None = None,
    title: str | None = None,
    link_context: LinkResolutionContext | None = None,
) -> PagerDocument:
    """Build one pager document containing one section per file path."""
    sections = path_sections(paths, cwd=cwd)
    return PagerDocument(
        sections=sections,
        title=title or _path_document_title(len(sections)),
        origin=PagerOrigin.FILE,
        link_context=default_link_context() if link_context is None else link_context,
    )


def path_sections(
    paths: Sequence[str | Path],
    *,
    cwd: str | Path | None = None,
) -> tuple[PagerSection, ...]:
    """Build pager sections by reading each file in *paths*."""
    return tuple(path_section(path, cwd=cwd) for path in paths)


def path_section(
    path: str | Path,
    *,
    cwd: str | Path | None = None,
    logical_filename: str | None = None,
    category: str = "raw_file",
    subject_ref: str | None = None,
    origin: PagerOrigin | None = None,
) -> PagerSection:
    """Build one file-backed pager section.

    Classification runs on the bytes already read for the section body.
    *logical_filename* is original source provenance when the resolved path
    is a content-addressed object; the default is the file's own path.
    Owner/checkout provenance is recovered from the landed path so later
    presses resolve in the file's repository rather than the viewer's cwd.
    """
    display_path = str(path)
    absolute_path = _absolute_path(path, cwd=cwd)
    body = absolute_path.read_text(encoding="utf-8", errors="replace")
    resolved_subject = subject_ref or f"file:{absolute_path}"
    anchor = link_anchor_for_directory(absolute_path.parent)
    filename = logical_filename or logical_source_filename(
        source_path=str(absolute_path)
    )
    return PagerSection(
        identity=resolved_subject,
        title=display_path,
        kind="file",
        body=body,
        subject_ref=resolved_subject,
        link_anchors=() if anchor is None else (anchor,),
        raw_source=classify_source(
            category=category,
            logical_filename=filename,
            source=body,
        ),
        origin=origin,
        owner=document_owner_from_path(
            absolute_path, source_reference=resolved_subject
        ),
    )


def _absolute_path(path: str | Path, *, cwd: str | Path | None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        base = Path.cwd() if cwd is None else Path(cwd).expanduser()
        candidate = base / candidate
    return candidate.resolve(strict=False)


def _path_document_title(count: int) -> str:
    return "1 file" if count == 1 else f"{count} files"


__all__ = [
    "document_from_paths",
    "path_section",
    "path_sections",
]
