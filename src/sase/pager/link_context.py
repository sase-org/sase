"""Ordered workspace anchors for pager link resolution.

These helpers are strictly read-only: they never call
``get_workspace_directory_for_num``, which cleans managed workspaces by
default. Missing directories, unreadable markers, and lookup failures
drop an anchor and keep going.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefDocumentOwner
from sase.sdd.files import get_primary_workspace_dir
from sase.workspace_provider.marker import find_marker_from_cwd
from sase.workspace_provider.utils import parse_workspace_dir


@dataclass(frozen=True, slots=True)
class LinkAnchor:
    """One directory the resolver may probe, with an optional workspace number."""

    directory: Path
    workspace_num: int | None = None


@dataclass(frozen=True, slots=True)
class LinkResolutionContext:
    """Ordered anchors for one press; first match wins.

    ``owner`` carries document/repository provenance for owned-source
    lookup. Combination of anchors stays in-memory and path-only.
    """

    anchors: tuple[LinkAnchor, ...] = ()
    owner: ArtifactRefDocumentOwner | None = None

    @property
    def base_dirs(self) -> tuple[Path, ...]:
        """Return the anchor directories in probe order."""
        return tuple(anchor.directory for anchor in self.anchors)


def default_link_context() -> LinkResolutionContext:
    """Anchor on cwd, then the primary workspace when it is distinct."""
    cwd = _existing_dir(Path.cwd())
    anchors: list[LinkAnchor] = []
    workspace_num: int | None = None
    if cwd is not None:
        workspace_num = _workspace_num_for(cwd)
        anchors.append(LinkAnchor(directory=cwd, workspace_num=workspace_num))
        primary = _primary_workspace_dir(cwd, workspace_num)
        if primary is not None:
            anchors.append(LinkAnchor(directory=primary, workspace_num=1))
    return LinkResolutionContext(anchors=_dedupe_anchors(anchors))


def agent_link_context(
    workspace_num: int | None,
    project_file: str | None,
    workspace_dir: str | Path | None = None,
) -> LinkResolutionContext:
    """Anchor on the agent's workspace, its primary, then the default list."""
    anchors: list[LinkAnchor] = []
    agent_dir = _agent_workspace_dir(workspace_num, project_file, workspace_dir)
    if agent_dir is not None:
        anchors.append(LinkAnchor(directory=agent_dir, workspace_num=workspace_num))
    primary = _existing_dir(_parse_primary_workspace(project_file))
    if primary is not None:
        anchors.append(LinkAnchor(directory=primary, workspace_num=1))
    anchors.extend(default_link_context().anchors)
    return LinkResolutionContext(anchors=_dedupe_anchors(anchors))


def workspace_link_context(
    workspace_dir: str | Path | None,
    *,
    workspace_num: int | None = None,
    include_default: bool = True,
) -> LinkResolutionContext:
    """Anchor on one workspace directory, its primary, then optional defaults."""
    anchors: list[LinkAnchor] = []
    workspace = _existing_dir(_path_input(workspace_dir))
    resolved_workspace_num = workspace_num
    if workspace is not None:
        if resolved_workspace_num is None:
            resolved_workspace_num = _workspace_num_for(workspace)
        anchors.append(
            LinkAnchor(directory=workspace, workspace_num=resolved_workspace_num)
        )
        primary = _primary_workspace_dir(workspace, resolved_workspace_num)
        if primary is not None:
            anchors.append(LinkAnchor(directory=primary, workspace_num=1))
    if include_default:
        anchors.extend(default_link_context().anchors)
    return LinkResolutionContext(anchors=_dedupe_anchors(anchors))


def inherited_link_context(
    landed_path: Path,
    parent_context: LinkResolutionContext,
    *,
    owner: ArtifactRefDocumentOwner | None = None,
) -> LinkResolutionContext:
    """Prepend the landed path's parent directory to *parent_context*."""
    parent_dir = _existing_dir(Path(landed_path).expanduser().parent)
    anchors: list[LinkAnchor] = []
    if parent_dir is not None:
        anchors.append(
            LinkAnchor(
                directory=parent_dir,
                workspace_num=_workspace_num_for(parent_dir),
            )
        )
    anchors.extend(parent_context.anchors)
    return LinkResolutionContext(
        anchors=_dedupe_anchors(anchors),
        owner=parent_context.owner if owner is None else owner,
    )


def link_anchor_for_directory(
    directory: str | Path | None,
    *,
    workspace_num: int | None = None,
) -> LinkAnchor | None:
    """Return one existence-checked directory anchor."""
    existing = _existing_dir(_path_input(directory))
    if existing is None:
        return None
    return LinkAnchor(
        directory=existing,
        workspace_num=(
            workspace_num if workspace_num is not None else _workspace_num_for(existing)
        ),
    )


def merge_link_context(
    link_anchors: Iterable[LinkAnchor] = (),
    document_context: LinkResolutionContext | None = None,
    *,
    owner: ArtifactRefDocumentOwner | None = None,
) -> LinkResolutionContext | None:
    """Prepend section anchors to a document context, preserving first match.

    Combination is in-memory: it does not stat, resolve, or otherwise
    normalize directories. First-anchor-wins is by the ``Path`` value as
    stored, not by filesystem identity. Section *owner* wins over the
    document owner when both are present.
    """
    anchors = list(link_anchors)
    merged_owner = owner
    if document_context is not None:
        anchors.extend(document_context.anchors)
        if merged_owner is None:
            merged_owner = document_context.owner
    merged = _unique_anchors(anchors)
    if not merged and merged_owner is None:
        return None
    return LinkResolutionContext(anchors=merged, owner=merged_owner)


def _agent_workspace_dir(
    workspace_num: int | None,
    project_file: str | None,
    workspace_dir: str | Path | None,
) -> Path | None:
    try:
        from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
            resolve_agent_workspace_dir,
        )

        resolved = resolve_agent_workspace_dir(
            workspace_num, project_file, workspace_dir
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if not resolved:
        return None
    return _existing_dir(Path(resolved))


def _path_input(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return Path(value)


def _parse_primary_workspace(project_file: str | None) -> Path | None:
    if project_file is None:
        return None
    try:
        parsed = parse_workspace_dir(project_file)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not parsed:
        return None
    return Path(parsed)


def _primary_workspace_dir(cwd: Path, workspace_num: int | None) -> Path | None:
    try:
        primary = get_primary_workspace_dir(str(cwd), workspace_num or 1)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not primary:
        return None
    return _existing_dir(Path(primary))


def _workspace_num_for(directory: Path) -> int | None:
    try:
        found = find_marker_from_cwd(str(directory))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if found is None:
        return None
    workspace_num = found[1].workspace_num
    return workspace_num if workspace_num > 0 else None


def _existing_dir(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return None
    if resolved.is_dir():
        return resolved
    return None


def _dedupe_anchors(anchors: Iterable[LinkAnchor]) -> tuple[LinkAnchor, ...]:
    checked: list[LinkAnchor] = []
    for anchor in anchors:
        directory = _existing_dir(anchor.directory)
        if directory is None:
            continue
        checked.append(
            LinkAnchor(directory=directory, workspace_num=anchor.workspace_num)
        )
    return _unique_anchors(checked)


def _unique_anchors(anchors: Iterable[LinkAnchor]) -> tuple[LinkAnchor, ...]:
    seen: set[Path] = set()
    unique: list[LinkAnchor] = []
    for anchor in anchors:
        if anchor.directory in seen:
            continue
        seen.add(anchor.directory)
        unique.append(anchor)
    return tuple(unique)


__all__ = [
    "LinkAnchor",
    "LinkResolutionContext",
    "agent_link_context",
    "default_link_context",
    "inherited_link_context",
    "link_anchor_for_directory",
    "merge_link_context",
    "workspace_link_context",
]
