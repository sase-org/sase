"""Shared environment variable contracts for SASE runtime coordination."""

from __future__ import annotations

import os
from collections.abc import Mapping

SASE_ACTIVE_PROJECT_DIR_ENV = "SASE_ACTIVE_PROJECT_DIR"
SASE_AGENT_WORKSPACE_NUM_ENV = "SASE_AGENT_WORKSPACE_NUM"
SASE_WORKSPACE_DIR_ENV_VARS: tuple[str, ...] = ("SASE_GIT_WORKSPACE_DIR",)
PROVIDER_PROJECT_DIR_ENV_VARS: tuple[str, ...] = (
    "CODEX_PROJECT_DIR",
    SASE_ACTIVE_PROJECT_DIR_ENV,
    "CLAUDE_PROJECT_DIR",
    "QWEN_PROJECT_DIR",
    # Antigravity CLI (`agy`) runs in the `.gemini` namespace it inherited from
    # the Gemini CLI and exports GEMINI_PROJECT_DIR for its workspace root.
    "GEMINI_PROJECT_DIR",
    "OPENCODE_PROJECT_DIR",
)
WORKSPACE_PIN_ENV_VARS: tuple[str, ...] = (
    *PROVIDER_PROJECT_DIR_ENV_VARS,
    *SASE_WORKSPACE_DIR_ENV_VARS,
)


def provider_project_dir_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Return the first runtime-provider project directory exported in ``env``."""
    values = os.environ if env is None else env
    for key in PROVIDER_PROJECT_DIR_ENV_VARS:
        value = values.get(key)
        if value:
            return value
    return None
