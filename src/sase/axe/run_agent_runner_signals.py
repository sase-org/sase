"""Signal-handling helpers for ``run_agent_runner``."""

import os
import signal
from collections.abc import Callable

from sase.axe.runner_signals import install_sigterm_handler, was_killed

_PENDING_HANDOFF_MARKERS = (".sase_plan_pending", ".sase_questions_pending")


def system_exit_code(exc: SystemExit) -> int | None:
    """Return the integer exit code for ``SystemExit`` when one is available."""
    return exc.code if isinstance(exc.code, int) else None


def is_user_kill_exit(exc: SystemExit) -> bool:
    """Return whether ``SystemExit`` represents an explicit user kill."""
    return was_killed() or system_exit_code(exc) == 128 + signal.SIGTERM


def _has_pending_handoff_marker(fallback_artifacts_dir: str | None = None) -> bool:
    """Return whether the current artifacts dir has a plan/question handoff."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR") or fallback_artifacts_dir
    if not artifacts_dir:
        return False

    try:
        return any(
            os.path.exists(os.path.join(artifacts_dir, marker))
            for marker in _PENDING_HANDOFF_MARKERS
        )
    except OSError:
        return False


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
        if _has_pending_handoff_marker(fallback_artifacts_dir):
            return
        from sase.running_field import release_workspace

        release_workspace(project_file, workspace_num, workflow_name, cl_name)

    install_sigterm_handler("agent", soft=True, on_signal=_release_workspace_claim)
