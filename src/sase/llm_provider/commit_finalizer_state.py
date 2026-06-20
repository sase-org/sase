"""Dirty repository discovery for commit finalization."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from sase.sibling_repos import (
    SIBLING_REPOS_JSON_ENV,
    opened_sibling_names,
    opened_sibling_workspace_dirs,
    sibling_repo_metadata_from_env,
)

from . import commit_finalizer_git as finalizer_git
from .commit_finalizer_git import git_changed_files
from .commit_finalizer_prompting import build_dirty_details
from .commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
    SiblingTarget,
    _WorkspaceStrategy,
)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
    "SASE_CD_WORKSPACE_NUM",
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
    opened_names = opened_sibling_names(artifact_root)
    opened_workspace_dirs = opened_sibling_workspace_dirs(artifact_root)
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
    advisory_sibling_repos = tuple(
        _dirty_configured_advisory_sibling_repos(sibling_targets)
    )
    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    details = build_dirty_details(
        main_details=main_details,
        main_instruction=main_instruction,
        main_repo=main_repo,
        sibling_repos=sibling_repos,
        advisory_sibling_repos=advisory_sibling_repos,
    )
    return DirtyState(
        project_dir=finalizer_git._normalize_path(project_dir),
        repos=tuple(repos),
        details=details,
        advisory_repos=advisory_sibling_repos,
    )


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

    for raw_name, recorded_workspace_dir in opened_workspace_dirs.items():
        name = raw_name.strip()
        if not name or name in seen_names:
            continue

        target = targets_by_name.get(name)
        if target is not None and target.workspace_strategy == "none":
            continue

        workspace_dir = recorded_workspace_dir.strip()
        if workspace_dir:
            workspace_dir = finalizer_git._normalize_path(workspace_dir)
        elif target is not None:
            workspace_dir = target.workspace_dir
        else:
            continue

        if workspace_dir in seen_paths:
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


def _dirty_configured_advisory_sibling_repos(
    sibling_targets: list[SiblingTarget],
) -> list[DirtyRepo]:
    return _dirty_configured_sibling_repos_for_strategy(
        sibling_targets,
        advisory=True,
        opened_names=None,
    )


def _dirty_configured_sibling_repos_for_strategy(
    sibling_targets: list[SiblingTarget],
    *,
    advisory: bool,
    opened_names: set[str] | None,
) -> list[DirtyRepo]:
    dirty: list[DirtyRepo] = []
    for target in sibling_targets:
        if (target.workspace_strategy == "none") != advisory:
            continue
        if opened_names is not None and target.name not in opened_names:
            continue
        changed_files = git_changed_files(target.workspace_dir)
        if not changed_files:
            continue
        dirty.append(
            DirtyRepo(
                name=target.name,
                path=target.workspace_dir,
                changed_files=tuple(changed_files),
                kind="sibling",
            )
        )
    return dirty


def _configured_sibling_targets(
    project_dir: str,
) -> list[SiblingTarget]:
    if SIBLING_REPOS_JSON_ENV in os.environ:
        return _sibling_targets_from_env()
    return _sibling_targets_from_config(project_dir)


def _sibling_targets_from_env() -> list[SiblingTarget]:
    targets: list[SiblingTarget] = []
    for index, item in enumerate(sibling_repo_metadata_from_env(os.environ), start=1):
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
                workspace_strategy=_sibling_workspace_strategy(
                    item.get("workspace_strategy")
                ),
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
        from sase.sibling_repos import resolve_sibling_repos_for_project

        resolution = resolve_sibling_repos_for_project(
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
            workspace_strategy=_sibling_workspace_strategy(repo.workspace_strategy),
        )
        for repo in resolution.repos
    ]


def _sibling_workspace_strategy(value: object) -> _WorkspaceStrategy:
    if value == "none":
        return "none"
    return "suffix"


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
