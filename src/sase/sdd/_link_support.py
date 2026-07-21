"""Shared helpers for resolving and pairing SDD artifact links."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._link_models import SddFile
from sase.sdd.artifact_links import (
    SddArtifactLink,
    SddArtifactLinkKind,
    SddArtifactLinkType,
)

PLAN_KINDS = ("tales", "epics")
PROMPT_KINDS = ("prompts", "specs")
LIST_KINDS = ("prompts", "plans", "tales", "epics")


def resolve_link_path(
    root: Path,
    source: Path,
    link: SddArtifactLink,
) -> Path | None:
    """Resolve a canonical href or compatible historical representation."""
    if link.kind is SddArtifactLinkKind.INVALID:
        return None
    if link.kind is SddArtifactLinkKind.MIXED and not mixed_link_agrees(
        root, source, link
    ):
        return None
    if link.kind in {SddArtifactLinkKind.CANONICAL, SddArtifactLinkKind.MIXED}:
        if link.target is None:
            return None
        return source.parent / Path(link.target)
    if link.kind is SddArtifactLinkKind.LEGACY and link.legacy is not None:
        return _resolve_legacy_representation(root, source, link)
    return None


def _resolve_legacy_representation(
    root: Path, source: Path, link: SddArtifactLink
) -> Path:
    assert link.legacy is not None
    if link.legacy.format == "markdown":
        return source.parent / Path(link.legacy.target)
    return resolve_legacy_link_path(root, link.legacy.target)


def mixed_link_agrees(root: Path, source: Path, link: SddArtifactLink) -> bool:
    """Compare mixed canonical/legacy representations by physical path."""
    if link.target is None or link.legacy is None:
        return False
    canonical = (source.parent / Path(link.target)).resolve()
    legacy = _resolve_legacy_representation(root, source, link).resolve()
    return canonical == legacy


def link_reference(root: Path, source: Path, link: SddArtifactLink) -> str | None:
    if link.kind is SddArtifactLinkKind.MIXED and mixed_link_agrees(root, source, link):
        return link.label
    return link.reference


def resolve_legacy_link_path(root: Path, link: str) -> Path:
    """Resolve a historical plain frontmatter path with legacy fallbacks."""
    link_path = Path(link)
    if link_path.is_absolute():
        return link_path

    candidates = [
        root / link_path,
        root.parent / link_path,
        root.parent.parent / link_path,
        Path.cwd() / link_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if link.startswith("sdd/") or link.startswith(".sase/sdd/"):
        return root.parent / link_path
    return root / link_path


def infer_counterpart(file: SddFile, files: list[SddFile]) -> list[SddFile]:
    wanted = set(PLAN_KINDS) if file.kind == "prompts" else {"prompts"}
    return [
        candidate
        for candidate in files
        if candidate.kind in wanted
        and candidate.yyyymm == file.yyyymm
        and candidate.name == file.name
    ]


def expected_link_type(file: SddFile) -> SddArtifactLinkType:
    return (
        SddArtifactLinkType.PLAN
        if file.kind == "prompts"
        else SddArtifactLinkType.PROMPT
    )


def relpath(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
