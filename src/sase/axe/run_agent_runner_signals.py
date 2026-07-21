"""Signal-handling helpers for ``run_agent_runner``."""

import os
import signal
from collections.abc import Callable

from sase.agent.pending_handoff import has_pending_handoff
from sase.axe.runner_signals import install_sigterm_handler, was_killed


def system_exit_code(exc: SystemExit) -> int | None:
    """Return the integer exit code for ``SystemExit`` when one is available."""
    return exc.code if isinstance(exc.code, int) else None


def is_user_kill_exit(exc: SystemExit) -> bool:
    """Return whether ``SystemExit`` represents an explicit user kill."""
    return was_killed() or system_exit_code(exc) == 128 + signal.SIGTERM


def install_workspace_release_sigterm_handler(
    *,
    project_file: str,
    workspace_num: int,
    workflow_name: str,
    cl_name: str,
    is_home_mode: bool,
    artifacts_dir_getter: Callable[[], str | None] | None = None,
) -> None:
    """Release this runner's workspace claim promptly on SIGTERM."""

    def _release_workspace_claim() -> None:
        if is_home_mode:
            return
        fallback_artifacts_dir = None
        if artifacts_dir_getter is not None:
            try:
                fallback_artifacts_dir = artifacts_dir_getter()
            except Exception:
                fallback_artifacts_dir = None
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR") or fallback_artifacts_dir
        if has_pending_handoff(artifacts_dir):
            return
        from sase.running_field import release_workspace

        release_workspace(project_file, workspace_num, workflow_name, cl_name)

    install_sigterm_handler("agent", soft=True, on_signal=_release_workspace_claim)
