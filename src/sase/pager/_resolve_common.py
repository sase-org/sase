"""Shared target builders for pager reference resolution."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
from sase.pager.adapters import path_section
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.known_kinds import known_kinds_from_link_context
from sase.pager.landings import binary_card_document
from sase.pager.link_context import LinkResolutionContext
from sase.pager.owner import document_owner_from_path, inherit_owner_context
from sase.pager.syntax_policy import is_openable_text_path
from sase.pager.targets import LinkTarget, LinkTargetKind

_MEDIA_MODES = frozenset({"image", "video", "pdf"})


def link_target_for_existing_path(
    path: Path,
    *,
    requested_line: int | None,
    requested_column: int | None = None,
    context: LinkResolutionContext,
) -> LinkTarget | None:
    if path.is_dir():
        return directory_link_target(path, context=context)

    mode = artifact_file_view_mode(path)
    if mode in _MEDIA_MODES:
        return LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(path, kind=mode),),
            edit_path=path,
            edit_line=requested_line,
            edit_column=requested_column,
        )
    if is_probably_text(path):
        return file_link_target(
            path,
            requested_line=requested_line,
            requested_column=requested_column,
            context=context,
        )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=binary_card_document(
            str(path),
            path=path,
            mime=_guess_mime(path),
            context=context,
        ),
        edit_path=path,
        edit_line=requested_line,
        edit_column=requested_column,
    )


def directory_link_target(
    path: Path,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return None
    lines = [f"{entry}{'/' if entry.is_dir() else ''}" for entry in entries]
    body = "\n".join(lines) + "\n" if lines else "(empty directory)\n"
    link_context = inherit_owner_context(path, context)
    document = PagerDocument(
        sections=(
            PagerSection(
                identity=f"file:{path}",
                title=str(path),
                kind="file",
                body=body,
                subject_ref=f"file:{path}",
                owner=document_owner_from_path(path, source_reference=f"file:{path}"),
                known_kinds=known_kinds_from_link_context(link_context),
            ),
        ),
        title=f"{len(entries)} entries · {path.name or str(path)}",
        origin=PagerOrigin.FILE,
        link_context=link_context,
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def file_link_target(
    path: Path,
    *,
    requested_line: int | None,
    requested_column: int | None = None,
    context: LinkResolutionContext | None = None,
    logical_filename: str | None = None,
    category: str = "raw_file",
    subject_ref: str | None = None,
) -> LinkTarget:
    section = path_section(
        path,
        logical_filename=logical_filename,
        category=category,
        subject_ref=subject_ref,
        known_kinds=known_kinds_from_link_context(context),
    )
    document = PagerDocument(
        sections=(section,),
        title=path.name,
        origin=PagerOrigin.FILE,
        link_context=inherit_owner_context(path, context),
    )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=document,
        scroll_line=requested_line,
        edit_path=path,
        edit_line=requested_line,
        edit_column=requested_column,
    )


def is_probably_text(
    path: Path,
    *,
    logical_filename: str | None = None,
) -> bool:
    return is_openable_text_path(
        path,
        logical_filename=logical_filename,
        mime=_guess_mime(path),
    )


def _guess_mime(path: Path) -> str | None:
    return mimetypes.guess_type(str(path))[0]


__all__ = [
    "directory_link_target",
    "file_link_target",
    "is_probably_text",
    "link_target_for_existing_path",
]
