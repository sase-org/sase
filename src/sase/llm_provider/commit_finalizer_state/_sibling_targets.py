"""Configured sibling-repo target resolution for commit finalization."""

from __future__ import annotations

import os

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    is_legacy_static_linked_repo_record,
    linked_repo_metadata_from_env,
)

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_types import SiblingTarget
from ._workspace_num import workspace_num_for_project_file


def configured_sibling_targets(project_dir: str) -> list[SiblingTarget]:
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
                workspace_dir=finalizer_git.normalize_path(workspace_dir),
            )
        )
    return targets


def _sibling_targets_from_config(
    project_dir: str,
) -> list[SiblingTarget]:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if not project_file:
        return []

    workspace_num = workspace_num_for_project_file(project_file, project_dir)
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
            workspace_dir=finalizer_git.normalize_path(repo.workspace_dir),
        )
        for repo in resolution.repos
    ]
