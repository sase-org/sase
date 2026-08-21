"""Workspace resolution for commit finalization."""

from __future__ import annotations

import os

from sase.env_contracts import (
    SASE_WORKSPACE_DIR_ENV_VARS,
    provider_project_dir_from_env,
)


_WORKSPACE_ENV_VARS = SASE_WORKSPACE_DIR_ENV_VARS


def resolve_finalizer_project_dir() -> str:
    """Resolve the workspace the finalizer should inspect."""
    if project_dir := provider_project_dir_from_env():
        return project_dir
    workspace = _workspace_env_value()
    if workspace:
        return workspace
    return os.getcwd()


def _workspace_env_value() -> str | None:
    for key in _WORKSPACE_ENV_VARS:
        value = os.environ.get(key)
        if value:
            return value
    return None


__all__ = ["resolve_finalizer_project_dir"]
