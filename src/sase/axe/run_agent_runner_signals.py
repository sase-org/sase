"""Signal-handling helpers for ``run_agent_runner``."""

import os
import signal
from collections.abc import Callable

from sase.axe.run_agent_monitor_handoff import monitor_handoff_claim_transferred
from sase.axe.runner_kill_provenance import snapshot_oom_baseline
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
    workspace_dir: str = "",
    artifacts_dir_getter: Callable[[], str | None] | None = None,
) -> None:
    """Release this runner's workspace claim promptly on SIGTERM."""

    snapshot_oom_baseline()

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
        if _has_hijack_intent(artifacts_dir):
            return
        if _has_staged_handoff(artifacts_dir):
            return
        if monitor_handoff_claim_transferred(
            project_file,
            workspace_num,
            cl_name=cl_name,
        ):
            return
        from sase.running_field import release_workspace
        from sase.workspace_provider.occupant import clear_occupant_record

        release_workspace(
            project_file,
            workspace_num,
            workflow_name,
            cl_name,
            expected_pid=os.getpid(),
        )
        clear_occupant_record(workspace_dir)

    install_sigterm_handler("agent", soft=True, on_signal=_release_workspace_claim)


def _has_hijack_intent(artifacts_dir: str | None) -> bool:
    """Return whether a hijack-mode user-kill marker keeps the claim on SIGTERM."""
    if not artifacts_dir:
        return False
    try:
        from sase.agent._user_kill_intent import has_hijack_intent

        return bool(has_hijack_intent(artifacts_dir))
    except Exception:  # noqa: BLE001 - signal guard fails open.
        return False


def _has_staged_handoff(artifacts_dir: str | None) -> bool:
    """Return whether staged state keeps the workspace claim on SIGTERM.

    Covers the valid record, the adoption receipt's held outcome, and
    malformed staged state: all three keep the claim until the post-workflow
    adoption boundary or the later reconciler, never the signal handler.
    """
    if not artifacts_dir:
        return False
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )

        try:
            if read_staged_handoff(artifacts_dir) is not None:
                return True
        except StagedHandoffError:
            return True
        try:
            receipt = read_adoption_receipt(artifacts_dir)
        except StagedHandoffError:
            return True
        except Exception:  # noqa: BLE001 - receipt read fails open.
            return False
        return receipt is not None
    except Exception:  # noqa: BLE001 - signal guard fails open.
        return False
