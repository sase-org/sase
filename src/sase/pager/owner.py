"""Recover document owner provenance for pager link resolution.

These helpers collect existing host metadata and adapt it to the Rust
``ArtifactRefDocumentOwner`` wire. They never clone or reset workspaces.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.artifact_cli.references import ResolvedArtifactReference
from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefDocumentOwner
from sase.pager.link_context import LinkResolutionContext, inherited_link_context
from sase.workspace_provider.marker import CheckoutMarker, find_marker_from_cwd


def document_owner_from_path(
    path: str | Path | None,
    *,
    source_reference: str | None = None,
) -> ArtifactRefDocumentOwner:
    """Build owner provenance from a landed file or directory path."""
    if path is None:
        return ArtifactRefDocumentOwner(source_reference=source_reference)
    resolved = _resolved_path(Path(path))
    directory = resolved if resolved.is_dir() else resolved.parent
    root = _vcs_root(directory)
    marker = _marker_for(root or directory)
    project_key = None if marker is None else (marker.project_key or None)
    return ArtifactRefDocumentOwner(
        source_reference=source_reference,
        project_key=project_key,
        source_directory=str(directory),
        checkout_candidates=() if root is None else (root,),
    )


def document_owner_from_artifact(
    result: ResolvedArtifactReference,
) -> ArtifactRefDocumentOwner:
    """Build owner provenance from a resolved artifact, even without a file row."""
    artifact_file = result.file
    resolved_path = result.resolution.resolved_path
    source_directory: str | None = None
    checkout_candidates: list[Path] = []
    project_key: str | None = None
    repository: str | None = None
    revision: str | None = None

    if artifact_file is not None:
        project_key = artifact_file.project
        repository = artifact_file.vcs_repo
        revision = artifact_file.vcs_sha
        if artifact_file.workspace_dir:
            workspace = _resolved_path(Path(artifact_file.workspace_dir))
            if workspace.is_dir():
                checkout_candidates.append(workspace)
        if artifact_file.source_path:
            source_directory = str(
                _resolved_path(Path(artifact_file.source_path)).parent
            )

    if resolved_path is not None:
        landed = _resolved_path(resolved_path)
        directory = landed if landed.is_dir() else landed.parent
        if source_directory is None:
            source_directory = str(directory)
        root = _vcs_root(directory)
        if root is not None:
            checkout_candidates.append(root)

    if result.context is not None:
        if project_key is None:
            project_key = result.context.selected_project
        for repository_record in result.context.repositories:
            checkout_candidates.extend(repository_record.checkout_paths)

    unique_checkouts = _unique_paths(checkout_candidates)
    if project_key is None:
        marker = _marker_for(unique_checkouts[0] if unique_checkouts else Path.cwd())
        if marker is not None:
            project_key = marker.project_key or None

    return ArtifactRefDocumentOwner(
        source_reference=result.canonical_reference,
        project_key=project_key,
        repository=repository,
        revision=revision,
        source_directory=source_directory,
        checkout_candidates=unique_checkouts,
    )


def inherit_owner_context(
    path: Path,
    context: LinkResolutionContext | None,
) -> LinkResolutionContext:
    """Prepend the landed parent and carry owner/project identity forward."""
    owner = document_owner_from_path(path, source_reference=f"file:{path}")
    if context is None:
        return inherited_link_context(path, LinkResolutionContext(), owner=owner)
    if context.owner is not None and owner.project_key is None:
        owner = replace(owner, project_key=context.owner.project_key)
    return inherited_link_context(path, context, owner=owner)


def artifact_context_for_link_context(
    context: LinkResolutionContext | None,
) -> ArtifactRefContext | None:
    """Build an artifact-ref context from the first usable owner or anchor."""
    if context is None:
        return None
    from sase.artifact_ref_context import artifact_ref_context

    for directory, workspace_num in _context_directories(context):
        try:
            return artifact_ref_context(directory, workspace_num or 1)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            continue
    return None


def owner_cache_key(
    owner: ArtifactRefDocumentOwner | None,
) -> tuple[str | None, str | None, str | None, str | None, tuple[str, ...]]:
    """Return a hashable identity for dangling-ref cache keys."""
    if owner is None:
        return (None, None, None, None, ())
    return (
        owner.source_reference,
        owner.project_key,
        owner.repository,
        owner.revision,
        tuple(str(path) for path in owner.checkout_candidates),
    )


def _context_directories(
    context: LinkResolutionContext,
) -> tuple[tuple[Path, int | None], ...]:
    seen: set[Path] = set()
    directories: list[tuple[Path, int | None]] = []

    def add(path: Path, workspace_num: int | None) -> None:
        resolved = _resolved_path(path)
        if resolved in seen:
            return
        seen.add(resolved)
        directories.append((resolved, workspace_num))

    owner = context.owner
    if owner is not None:
        if owner.source_directory:
            add(Path(owner.source_directory), None)
        for checkout in owner.checkout_candidates:
            add(checkout, None)
    for anchor in context.anchors:
        add(anchor.directory, anchor.workspace_num)
    return tuple(directories)


def _vcs_root(path: Path) -> Path | None:
    candidate = _resolved_path(path)
    if not candidate.is_dir():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists() or (directory / ".hg").exists():
            return directory
    return None


def _marker_for(directory: Path) -> CheckoutMarker | None:
    try:
        found = find_marker_from_cwd(str(directory))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if found is None:
        return None
    return found[1]


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = _resolved_path(path)
        if not resolved.is_dir() or resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique)


def _resolved_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser()


__all__ = [
    "artifact_context_for_link_context",
    "document_owner_from_artifact",
    "document_owner_from_path",
    "inherit_owner_context",
    "owner_cache_key",
]
