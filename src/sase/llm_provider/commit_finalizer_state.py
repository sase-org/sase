"""Dirty repository discovery for commit finalization."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    linked_repo_metadata_from_env,
    is_legacy_static_linked_repo_record,
    opened_linked_repo_names,
    opened_linked_repo_workspace_dirs,
)

from . import commit_finalizer_git as finalizer_git
from .commit_finalizer_git import git_changed_files
from .commit_finalizer_prompting import build_dirty_details
from .commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
    SiblingTarget,
)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)


def collect_dirty_state(
    project_dir: str,
    *,
    artifact_root: Path | None = None,
) -> DirtyState:
    has_main_changes, main_files, main_instruction, main_details = (
        _build_commit_details(project_dir)
    )

    main_repo = (
        DirtyRepo(
            name="main",
            path=finalizer_git._normalize_path(project_dir),
            changed_files=tuple(main_files),
            kind="main",
        )
        if has_main_changes
        else None
    )
    sibling_targets = _configured_sibling_targets(project_dir)
    opened_names = opened_linked_repo_names(artifact_root)
    opened_workspace_dirs = opened_linked_repo_workspace_dirs(artifact_root)
    if opened_names:
        opened_workspace_dirs = {
            **dict.fromkeys(sorted(opened_names), ""),
            **opened_workspace_dirs,
        }
    sibling_repos = tuple(
        _dirty_configured_sibling_repos(
            sibling_targets,
            opened_workspace_dirs=opened_workspace_dirs,
        )
    )
    sdd_repos = tuple(_dirty_sdd_store_repos(project_dir))
    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    repos.extend(sdd_repos)
    details = build_dirty_details(
        main_details=main_details,
        main_instruction=main_instruction,
        main_repo=main_repo,
        sibling_repos=sibling_repos,
        sdd_repos=sdd_repos,
    )
    return DirtyState(
        project_dir=finalizer_git._normalize_path(project_dir),
        repos=tuple(repos),
        details=details,
    )


def _dirty_sdd_store_repos(project_dir: str) -> list[DirtyRepo]:
    """Return dirty external SDD repositories owned by this workspace."""

    try:
        from sase.sdd._commit_store import sdd_commit_targets, sdd_store_label
        from sase.sdd.store import (
            SDD_STORAGE_COMPANION_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        workspace_num = None
        if project_file:
            workspace_num = _workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is None:
            workspace_num = _workspace_num_from_env()
        store = resolve_sdd_store(project_dir, workspace_num or 1)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_COMPANION_REPOS,
        }:
            return []

        dirty: list[DirtyRepo] = []
        targets = sdd_commit_targets(store, None)
        for index, (target_store, _paths) in enumerate(targets):
            repo_root = target_store.repo_root.expanduser()
            if not (repo_root / ".git").exists():
                continue
            changed_files = git_changed_files(str(repo_root))
            if not changed_files:
                continue
            fallback = (
                "research"
                if store.is_companion_storage and index == 1
                else "plans"
                if store.is_companion_storage
                else "sdd"
            )
            dirty.append(
                DirtyRepo(
                    name=sdd_store_label(target_store) or fallback,
                    path=finalizer_git._normalize_path(str(repo_root)),
                    changed_files=tuple(changed_files),
                    kind="sdd",
                )
            )
        return dirty
    except Exception:
        return []


def _build_commit_details(project_dir: str) -> tuple[bool, list[str], str, str]:
    from . import commit_finalizer

    return commit_finalizer.build_commit_details(project_dir)


def _dirty_configured_sibling_repos(
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
            workspace_dir = finalizer_git._normalize_path(workspace_dir)
        elif target is not None:
            workspace_dir = target.workspace_dir
        else:
            continue

        candidates.append((name, workspace_dir))

    for target in sibling_targets:
        candidates.append((target.name, target.workspace_dir))

    return candidates


def _configured_sibling_targets(
    project_dir: str,
) -> list[SiblingTarget]:
    # Prefer the canonical linked env var and fall back to the deprecated
    # sibling env var so old launches still drive finalizer behavior.
    if LINKED_REPOS_JSON_ENV in os.environ or SIBLING_REPOS_JSON_ENV in os.environ:
        return _sibling_targets_from_env()
    return _sibling_targets_from_config(project_dir)


def _sibling_targets_from_env() -> list[SiblingTarget]:
    targets: list[SiblingTarget] = []
    for index, item in enumerate(linked_repo_metadata_from_env(os.environ), start=1):
        if is_legacy_static_linked_repo_record(item):
            continue
        workspace_dir = item.get("workspace_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir.strip():
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"sibling_{index}"
        targets.append(
            SiblingTarget(
                name=name.strip(),
                workspace_dir=finalizer_git._normalize_path(workspace_dir),
            )
        )
    return targets


def _sibling_targets_from_config(
    project_dir: str,
) -> list[SiblingTarget]:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if not project_file:
        return []

    workspace_num = _workspace_num_for_project_file(project_file, project_dir)
    if workspace_num is None:
        return []

    try:
        from sase.linked_repos import resolve_linked_repos_for_project

        resolution = resolve_linked_repos_for_project(
            project_file=project_file,
            workspace_dir=project_dir,
            workspace_num=workspace_num,
            materialize=False,
        )
    except Exception:
        return []

    return [
        SiblingTarget(
            name=repo.name,
            workspace_dir=finalizer_git._normalize_path(repo.workspace_dir),
        )
        for repo in resolution.repos
    ]


def _workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = _workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(finalizer_git._normalize_path(primary_dir))
    project_path = Path(finalizer_git._normalize_path(project_dir))
    if project_path == primary_path:
        return 0
    if project_path.parent != primary_path.parent:
        return None

    prefix = f"{primary_path.name}_"
    if not project_path.name.startswith(prefix):
        return None
    suffix = project_path.name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _workspace_num_from_env() -> int | None:
    for key in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None
