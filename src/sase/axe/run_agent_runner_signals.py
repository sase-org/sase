"""Signal-handling helpers for ``run_agent_runner``."""

import os
import signal
from collections.abc import Callable
from pathlib import Path

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER, PENDING_HANDOFF_MARKERS
from sase.axe.run_agent_monitor_handoff import monitor_handoff_claim_transferred
from sase.axe.runner_signals import install_sigterm_handler, was_killed

_NON_MONITOR_HANDOFF_MARKERS = tuple(
    marker for marker in PENDING_HANDOFF_MARKERS if marker != MONITOR_PENDING_MARKER
)


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
    workspace_dir: str = "",
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
        if _has_pending_handoff_marker(
            artifacts_dir, markers=_NON_MONITOR_HANDOFF_MARKERS
        ):
            return
        if _has_pending_handoff_marker(
            artifacts_dir, markers=(MONITOR_PENDING_MARKER,)
        ) and monitor_handoff_claim_transferred(
            project_file,
            workspace_num,
            cl_name=cl_name,
        ):
            return
        from sase.running_field import release_workspace
        from sase.workspace_provider.occupant import clear_occupant_record

        release_workspace(project_file, workspace_num, workflow_name, cl_name)
        clear_occupant_record(workspace_dir)

    install_sigterm_handler("agent", soft=True, on_signal=_release_workspace_claim)


def _has_pending_handoff_marker(
    artifacts_dir: str | None,
    *,
    markers: tuple[str, ...],
) -> bool:
    if not artifacts_dir:
        return False
    try:
        artifacts_path = Path(artifacts_dir)
        return any((artifacts_path / marker).exists() for marker in markers)
    except OSError:
        return False
