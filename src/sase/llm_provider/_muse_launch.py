"""Launch helpers for the Muse provider: executable, sandbox, prompts.

:mod:`sase.llm_provider.muse_provider` imports the public names below; no
``_``-prefixed name is imported across modules.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from sase.core.paths import get_sase_managed_tmpdir

_MUSE_PATH_ENV = "SASE_MUSE_PATH"
MUSE_CLI_NAME = "muse"
_MUSE_SANDBOX_ENV = "SASE_MUSE_SANDBOX"

# The launcher otherwise checks for and swaps in a new binary hourly; a
# multi-hour agent run must not have its binary replaced mid-flight. Users
# update Muse through `sase agent-cli update muse` instead.
MUSE_NO_AUTO_UPDATE_ENV = "MUSE_NO_AUTO_UPDATE"

_PROMPT_FILE_TMPDIR_PART = "muse-prompts"

# Muse accepts every canonical level. Meta documents ``max`` reasoning for the
# standard Spark 1.3 model only; explicit requests for other model versions are
# left to the CLI to validate. Muse's own default is ``high``, so a run with no
# resolved effort shows blank in SASE while Muse actually used ``high``.
MUSE_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--reasoning-effort", level]
    for level in ("none", "minimal", "low", "medium", "high", "xhigh", "max")
}


def resolve_muse_executable() -> str:
    """Return the Muse executable SASE should launch."""
    explicit_path = os.environ.get(_MUSE_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which(MUSE_CLI_NAME)
    if path_result:
        return path_result

    return MUSE_CLI_NAME


def muse_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Muse diagnostic."""
    return FileNotFoundError(
        "Unable to launch Muse Code executable "
        f"{command!r}. Set SASE_MUSE_PATH to the Muse binary, ensure 'muse' is "
        "discoverable on PATH, or run `sase agent-cli install muse`."
    )


def _muse_sandbox_enabled() -> bool:
    """Return whether the hardened ``SASE_MUSE_SANDBOX=on`` mode is requested."""
    return os.environ.get(_MUSE_SANDBOX_ENV, "").strip().lower() == "on"


def muse_safety_args() -> list[str]:
    """Return the safety flags for this run's sandbox mode.

    Muse's sandbox makes ``.git``, ``.muse``, and ``.agents`` read-only inside
    the workspace root, which breaks any in-run ``sase stitch create`` the agent
    performs through the ``sase_git_commit`` skill. The default therefore
    disables it, matching what SASE already does for Codex and OpenCode.
    ``SASE_MUSE_SANDBOX=on`` keeps the sandbox with networking enabled, which
    is genuinely useful for read-only research agents — at the documented cost
    of in-run commits failing.
    """
    if _muse_sandbox_enabled():
        return ["--sandbox-network", "enabled"]
    return ["--disable-sandbox"]


def write_muse_prompt_file(prompt: str) -> str:
    """Write *prompt* to a ``0o600`` file under SASE's managed temp root.

    ``muse exec`` reserves stdin for ``--api-key-stdin`` and SASE prompts
    routinely exceed comfortable argv limits, so ``--prompt-file`` is the only
    workable channel.
    """
    directory = get_sase_managed_tmpdir(_PROMPT_FILE_TMPDIR_PART)
    path = Path(directory) / f"prompt-{os.getpid()}-{uuid.uuid4().hex}.md"
    path.touch(mode=0o600)
    path.write_text(prompt, encoding="utf-8")
    return str(path)


def log_muse_interrupt(message: str | None, cycle: int) -> None:
    """Append an interrupt entry to the artifacts directory."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "interrupt_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(
                {"message": message, "timestamp": time.time(), "cycle": cycle},
                f,
            )
            f.write("\n")
    except OSError:
        pass


__all__ = [
    "MUSE_CLI_NAME",
    "MUSE_EFFORT_CLI_ARGS",
    "MUSE_NO_AUTO_UPDATE_ENV",
    "log_muse_interrupt",
    "muse_executable_not_found_error",
    "muse_safety_args",
    "resolve_muse_executable",
    "write_muse_prompt_file",
]
