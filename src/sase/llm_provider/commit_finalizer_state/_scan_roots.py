"""Scan-root enumeration shared by dirty-state collection and write guards.

:func:`commit_scan_roots` returns the normalized checkout paths the commit
finalizer scans, in scan order, without making any git status calls. It
mirrors the target enumeration in :func:`collect_dirty_state` so detectors
can tell whether a write sits in a checkout the host will commit.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.linked_repos import (
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_workspace_dirs,
)

from .. import commit_finalizer_git as finalizer_git
from ._dirty_repos import (
    known_sdd_sidecar_paths as _known_sdd_sidecar_paths,
)
from ._sibling_targets import configured_sibling_targets as _configured_sibling_targets

if TYPE_CHECKING:
    from ..commit_finalizer_types import SiblingTarget


def commit_scan_roots(
    project_dir: str,
    artifact_root: Path | None = None,
) -> tuple[str, ...]:
    """Return normalized scan roots in ``collect_dirty_state`` order.

    The roots are the main project dir, configured sibling target dirs with
    name-only opens resolved through sibling targets exactly as
    ``_blocking_sibling_candidates`` does, opened external workspace dirs,
    and known SDD and agents-archive paths. The result is deduped with
    first-seen order preserved. This function makes no git status calls.
    """

    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        normalized = finalizer_git.normalize_path(path)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    _add(project_dir)

    sibling_targets = _configured_sibling_targets(project_dir)
    targets_by_name = {target.name: target for target in sibling_targets}
    opened_workspace_dirs = _merged_opened_workspace_dirs(artifact_root)
    for _name, workspace_dir in _blocking_candidates(
        sibling_targets,
        opened_workspace_dirs,
        targets_by_name,
    ):
        _add(workspace_dir)

    try:
        external_records = opened_external_repo_records(artifact_root)
    except Exception:
        external_records = {}
    for _name, record in external_records.items():
        workspace_dir = (record.get("workspace_dir") or "").strip()
        if workspace_dir:
            _add(workspace_dir)

    try:
        known_sdd_paths = _known_sdd_sidecar_paths(project_dir)
    except Exception:
        known_sdd_paths = {}
    for path in known_sdd_paths:
        _add(path)

    return tuple(ordered)


def _merged_opened_workspace_dirs(
    artifact_root: Path | None,
) -> dict[str, str]:
    """Merge opened linked names and dirs like ``collect_dirty_state`` does."""

    try:
        opened_names = opened_linked_repo_names(artifact_root)
    except Exception:
        opened_names = set()
    try:
        opened_workspace_dirs = dict(opened_linked_repo_workspace_dirs(artifact_root))
    except Exception:
        opened_workspace_dirs = {}
    if opened_names:
        opened_workspace_dirs = {
            **dict.fromkeys(sorted(opened_names), ""),
            **opened_workspace_dirs,
        }
    return opened_workspace_dirs


def _blocking_candidates(
    sibling_targets: list[SiblingTarget],
    opened_workspace_dirs: dict[str, str],
    targets_by_name: dict[str, SiblingTarget],
) -> list[tuple[str, str]]:
    """Resolve opened dirs exactly as ``_blocking_sibling_candidates`` does."""

    candidates: list[tuple[str, str]] = []
    for raw_name, recorded_workspace_dir in opened_workspace_dirs.items():
        name = raw_name.strip()
        if not name:
            continue
        target = targets_by_name.get(name)
        workspace_dir = recorded_workspace_dir.strip()
        if workspace_dir:
            workspace_dir = finalizer_git.normalize_path(workspace_dir)
        elif target is not None:
            workspace_dir = target.workspace_dir
        else:
            continue
        candidates.append((name, workspace_dir))
    for target in sibling_targets:
        candidates.append((target.name, target.workspace_dir))
    return candidates


__all__ = ["commit_scan_roots"]
