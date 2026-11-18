"""Ordered repository-candidate enumeration shared by finalizer and guard.

This module owns the single target enumeration used by both the actual
dirty-state collector and the unscanned-write guard. It makes no git status
calls: callers gather status facts once per normalized checkout and pass
those facts to the shared Rust policy.
"""

from __future__ import annotations

from pathlib import Path

import os

from sase.linked_repos import (
    HIDDEN_SIDECAR_ROLES,
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_workspace_dirs,
)

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_types import SiblingTarget
from ._sibling_targets import configured_sibling_targets as _configured_sibling_targets
from ._workspace_num import (
    workspace_num_for_project_file,
    workspace_num_from_env,
)


def repository_candidates(
    project_dir: str,
    artifact_root: Path | None = None,
) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """Return ordered ``(name, path, kind)`` candidates plus SDD paths.

    Order is main, sibling candidates in opened-then-configured order with
    name-only opens resolved through sibling targets, opened external
    workspace dirs, then known SDD and agents-archive paths. Paths are
    normalized; the enumeration itself makes no git status calls.
    """

    ordered: list[tuple[str, str, str]] = []
    ordered.append(("main", finalizer_git.normalize_path(project_dir), "main"))

    sibling_targets = _configured_sibling_targets(project_dir)
    targets_by_name = {target.name: target for target in sibling_targets}
    opened_workspace_dirs = _merged_opened_workspace_dirs(artifact_root)
    for name, workspace_dir in sibling_candidates(
        sibling_targets,
        opened_workspace_dirs,
        targets_by_name,
    ):
        ordered.append((name, workspace_dir, "sibling"))

    try:
        external_records = opened_external_repo_records(artifact_root)
    except Exception:
        external_records = {}
    for name, record in external_records.items():
        workspace_dir = (record.get("workspace_dir") or "").strip()
        if not workspace_dir:
            continue
        canonical = (record.get("ref") or name).strip() or name
        ordered.append(
            (canonical, finalizer_git.normalize_path(workspace_dir), "external")
        )

    try:
        known_sdd_paths = known_sdd_sidecar_paths(project_dir)
    except Exception:
        known_sdd_paths = {}
    for path in known_sdd_paths:
        ordered.append((known_sdd_paths[path], path, "sdd"))

    return ordered, dict(known_sdd_paths)


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


def sibling_candidates(
    sibling_targets: list[SiblingTarget],
    opened_workspace_dirs: dict[str, str],
    targets_by_name: dict[str, SiblingTarget],
) -> list[tuple[str, str]]:
    """Resolve opened dirs exactly as the finalizer selection does."""

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


__all__ = ["known_sdd_sidecar_paths", "repository_candidates", "sibling_candidates"]


def known_sdd_sidecar_paths(project_dir: str) -> dict[str, str]:
    """Map normalized path to display name for configured SDD sidecars.

    This is the stable identity used to keep one scan per repository path:
    a path known to be an SDD sidecar is always classified as ``sdd`` even
    when a configured sibling target also names it, so a bead-sidecar
    sync/rebase between two ``git status`` calls cannot surface the same
    checkout as ``sibling:beads`` on one scan and ``sdd:beads`` on another.
    """

    mapping: dict[str, str] = {}
    for name, path in _sdd_store_identities(project_dir):
        mapping.setdefault(finalizer_git.normalize_path(path), name)
    archive = _agents_prompt_archive_identity(project_dir)
    if archive is not None:
        name, path = archive
        mapping.setdefault(finalizer_git.normalize_path(path), name)
    return mapping


def _sdd_store_identities(project_dir: str) -> list[tuple[str, str]]:
    """Return ``(name, path)`` for SDD sidecar checkouts without status calls."""

    try:
        from sase.sdd._commit_store import sdd_commit_targets, sdd_store_label
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        workspace_num = None
        if project_file:
            workspace_num = workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is None:
            workspace_num = workspace_num_from_env()
        store = resolve_sdd_store(project_dir, workspace_num or 1)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return []

        identities: list[tuple[str, str]] = []
        for target_store, _paths in sdd_commit_targets(store, None):
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not (repo_root / ".git").exists():
                continue
            identities.append(
                (
                    sdd_store_label(target_store) or target_store.sidecar_role or "sdd",
                    str(repo_root),
                )
            )
        return identities
    except Exception:
        return []


def _agents_prompt_archive_identity(project_dir: str) -> tuple[str, str] | None:
    """Return ``(name, path)`` for the agents prompt-archive checkout, if any."""

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return None
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not (agents_root / ".git").exists():
            return None
        return ("agents prompt archive", str(agents_root))
    except Exception:
        return None
