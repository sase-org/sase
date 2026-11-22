"""Shared environment variable contracts for SASE runtime coordination."""

from __future__ import annotations

import os
from collections.abc import Mapping

SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV = "SASE_PROVIDER_SYNC_CEILING_SECONDS"
SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV = "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS"
SASE_ACTIVE_PROJECT_DIR_ENV = "SASE_ACTIVE_PROJECT_DIR"
SASE_AGENT_WORKSPACE_NUM_ENV = "SASE_AGENT_WORKSPACE_NUM"
SASE_HOST_PATH_SNAPSHOT_ENV = "SASE_HOST_PATH_SNAPSHOT"
#: Path of the shadow-rendered instruction bundle for the current root
#: provider invocation. Exported only while ``provider.invoke`` runs inside
#: the instruction shadow boundary (E2); restored afterwards.
SASE_INSTRUCTIONS_FILE_ENV = "SASE_INSTRUCTIONS_FILE"
SASE_LAUNCH_SCRATCH_KEY_ENV = "SASE_LAUNCH_SCRATCH_KEY"
SASE_LAUNCH_SUBMITTED_AT_ENV = "SASE_LAUNCH_SUBMITTED_AT"
SASE_WORKSPACE_DIR_ENV_VARS: tuple[str, ...] = ("SASE_GIT_WORKSPACE_DIR",)
#: Set to ``0`` to keep every dependency or time wait in the full runner process
#: instead of exec'ing the lean waiter (``axe/run_agent_lean_wait.py``). A
#: diagnostic override, like ``SASE_TUI_GC_POLICY_DISABLE``; unset means lean.
SASE_RUNNER_LEAN_WAIT_ENV = "SASE_RUNNER_LEAN_WAIT"
#: JSON handoff spec the runner passes to the lean waiter across ``exec``.
SASE_RUNNER_LEAN_WAIT_SPEC_ENV = "SASE_RUNNER_LEAN_WAIT_SPEC"
#: JSON outcome the lean waiter passes back to the runner across ``exec``.
SASE_RUNNER_LEAN_WAIT_RESULT_ENV = "SASE_RUNNER_LEAN_WAIT_RESULT"
#: One-shot guard marking a runner pass that already crossed its wait, whether
#: through a code refresh re-exec or the lean waiter's return exec.
SASE_RUNNER_CODE_REFRESHED_ENV = "SASE_RUNNER_CODE_REFRESHED"
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
