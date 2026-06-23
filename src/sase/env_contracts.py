"""Shared environment variable contracts for SASE runtime coordination."""

SASE_ACTIVE_PROJECT_DIR_ENV = "SASE_ACTIVE_PROJECT_DIR"
SASE_WORKSPACE_DIR_ENV_VARS: tuple[str, ...] = (
    "SASE_GIT_WORKSPACE_DIR",
    "SASE_CD_WORKSPACE_DIR",
)
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
