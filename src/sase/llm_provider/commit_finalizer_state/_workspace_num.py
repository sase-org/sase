"""Workspace-number resolution shared by commit finalizer repo discovery."""

from __future__ import annotations

import os
from pathlib import Path

from .. import commit_finalizer_git as finalizer_git

WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)


def workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(finalizer_git.normalize_path(primary_dir))
    project_path = Path(finalizer_git.normalize_path(project_dir))
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


def workspace_num_from_env() -> int | None:
    for key in WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None
