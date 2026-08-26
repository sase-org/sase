"""Adapters that build pager documents from existing SASE inputs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


def document_from_paths(
    paths: Sequence[str | Path],
    *,
    cwd: str | Path | None = None,
    title: str | None = None,
) -> PagerDocument:
    """Build one pager document containing one section per file path."""
    sections = path_sections(paths, cwd=cwd)
    return PagerDocument(
        sections=sections,
        title=title or _path_document_title(len(sections)),
        origin=PagerOrigin.FILE,
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
) -> PagerSection:
    """Build one file-backed pager section."""
    display_path = str(path)
    absolute_path = _absolute_path(path, cwd=cwd)
    body = absolute_path.read_text(encoding="utf-8", errors="replace")
    subject_ref = f"file:{absolute_path}"
    return PagerSection(
        identity=subject_ref,
        title=display_path,
        kind="file",
        body=body,
        subject_ref=subject_ref,
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
