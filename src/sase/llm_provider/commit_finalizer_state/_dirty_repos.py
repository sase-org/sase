"""Per-source dirty-repository discovery for commit finalization."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from sase.linked_repos import HIDDEN_SIDECAR_ROLES

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_git import git_changed_files, is_prompt_archive_path
from ..commit_finalizer_types import DirtyRepo, SiblingTarget
from ._workspace_num import workspace_num_for_project_file, workspace_num_from_env


def dirty_opened_external_repos(
    records: Mapping[str, Mapping[str, str]],
) -> list[DirtyRepo]:
    """Return dirty external repositories recorded in this agent run."""

    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for name, record in records.items():
        canonical_name = (record.get("ref") or name).strip()
        workspace_dir = record.get("workspace_dir", "").strip()
        if not canonical_name or not workspace_dir:
            continue
        workspace_dir = finalizer_git.normalize_path(workspace_dir)
        if canonical_name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue
        dirty.append(
            DirtyRepo(
                name=canonical_name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="external",
            )
        )
        seen_names.add(canonical_name)
        seen_paths.add(workspace_dir)
    return dirty


def dirty_sdd_store_repos(project_dir: str) -> list[DirtyRepo]:
    """Return dirty external SDD repositories owned by this workspace."""

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

        dirty: list[DirtyRepo] = []
        targets = sdd_commit_targets(store, None)
        for target_store, _paths in targets:
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not (repo_root / ".git").exists():
                continue
            changed_files = git_changed_files(str(repo_root))
            if not changed_files:
                continue
            dirty.append(
                DirtyRepo(
                    name=(
                        sdd_store_label(target_store)
                        or target_store.sidecar_role
                        or "sdd"
                    ),
                    path=finalizer_git.normalize_path(str(repo_root)),
                    changed_files=tuple(changed_files),
                    kind="sdd",
                )
            )
        return dirty
    except Exception:
        return []


def dirty_agents_prompt_archive_repo(project_dir: str) -> list[DirtyRepo]:
    """Return a dirty agents sidecar only for canonical prompt-file edits."""

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return []
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not (agents_root / ".git").exists():
            return []
        changed_files = git_changed_files(str(agents_root))
        if not changed_files or not all(
            is_prompt_archive_path(path) for path in changed_files
        ):
            return []
        return [
            DirtyRepo(
                name="agents prompt archive",
                path=finalizer_git.normalize_path(str(agents_root)),
                changed_files=tuple(changed_files),
                kind="sdd",
            )
        ]
    except Exception:
        return []


def dirty_configured_sibling_repos(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str] | None = None,
    opened_names: set[str] | None = None,
) -> list[DirtyRepo]:
    if opened_workspace_dirs is None:
        opened_workspace_dirs = dict.fromkeys(sorted(opened_names or set()), "")

    targets_by_name = {target.name: target for target in sibling_targets}
    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()

    for name, workspace_dir in _blocking_sibling_candidates(
        sibling_targets,
        opened_workspace_dirs=opened_workspace_dirs,
        targets_by_name=targets_by_name,
    ):
        if name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue

        dirty.append(
            DirtyRepo(
                name=name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="sibling",
            )
        )
        seen_names.add(name)
        seen_paths.add(workspace_dir)
    return dirty


def _blocking_sibling_candidates(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str],
    targets_by_name: Mapping[str, SiblingTarget],
) -> list[tuple[str, str]]:
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
