"""Configuration and workspace resolution for commit finalization."""

from __future__ import annotations

import os
from typing import Any

from sase.config.core import load_merged_config
from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV

from .commit_finalizer_types import (
    _DEFAULT_ENABLED,
    _DEFAULT_MAX_PASSES,
    CommitFinalizerConfig,
)

_WORKSPACE_ENV_VARS: tuple[str, ...] = (
    "SASE_GIT_WORKSPACE_DIR",
    "SASE_CD_WORKSPACE_DIR",
)
_PROVIDER_PROJECT_ENV_VARS: tuple[str, ...] = (
    "CODEX_PROJECT_DIR",
    SASE_ACTIVE_PROJECT_DIR_ENV,
    "CLAUDE_PROJECT_DIR",
    "QWEN_PROJECT_DIR",
    # Antigravity CLI (`agy`) runs in the `.gemini` namespace it inherited from
    # the Gemini CLI and exports GEMINI_PROJECT_DIR for its workspace root.
    "GEMINI_PROJECT_DIR",
    "OPENCODE_PROJECT_DIR",
)


def resolve_finalizer_project_dir() -> str:
    """Resolve the workspace the finalizer should inspect."""
    for key in _PROVIDER_PROJECT_ENV_VARS:
        candidate = os.environ.get(key)
        if candidate:
            return candidate
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


def load_finalizer_config() -> CommitFinalizerConfig:
    try:
        config = load_merged_config()
    except Exception:
        return CommitFinalizerConfig()

    commit_config = config.get("commit", {})
    if not isinstance(commit_config, dict):
        return CommitFinalizerConfig()
    finalizer_config = commit_config.get("finalizer", {})
    if not isinstance(finalizer_config, dict):
        return CommitFinalizerConfig()

    enabled = finalizer_config.get("enabled", _DEFAULT_ENABLED)
    max_passes = finalizer_config.get("max_passes", _DEFAULT_MAX_PASSES)
    return CommitFinalizerConfig(
        enabled=enabled if isinstance(enabled, bool) else _DEFAULT_ENABLED,
        max_passes=_normalize_max_passes(max_passes),
    )


def _normalize_max_passes(value: Any) -> int:
    if isinstance(value, bool):
        return _DEFAULT_MAX_PASSES
    try:
        max_passes = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PASSES
    return max(1, max_passes)
