"""Rollback helpers for launches that fail after spawning child agents."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import signal
from collections.abc import Sequence

from sase.agent.launch_types import AgentLaunchResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PartialLaunchRollbackResult:
    """Summary of best-effort partial-launch cleanup."""

    terminated_pids: tuple[int, ...]
    released_workspaces: tuple[tuple[str, int], ...]


def rollback_partial_launch_results(
    results: Sequence[AgentLaunchResult],
) -> _PartialLaunchRollbackResult:
    """Terminate spawned children and release their workspace claims."""
    terminated: list[int] = []
    released: list[tuple[str, int]] = []

    for result in results:
        if _terminate_process_group(result.pid):
            terminated.append(result.pid)
        if _release_workspace_claim(result):
            released.append((result.project_file, result.workspace_num))

    return _PartialLaunchRollbackResult(
        terminated_pids=tuple(terminated),
        released_workspaces=tuple(released),
    )


def _terminate_process_group(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        log.warning("Permission denied terminating partial-launch pid %s", pid)
        return False
    except OSError:
        log.exception("Failed to terminate partial-launch pid %s", pid)
        return False


def _release_workspace_claim(result: AgentLaunchResult) -> bool:
    if not result.project_file:
        return False
    try:
        from sase.running_field import release_workspace

        release_workspace(
            result.project_file,
            result.workspace_num,
            result.workflow_name or None,
            result.cl_name or None,
        )
        return True
    except Exception:
        log.exception(
            "Failed to release workspace #%s for partial-launch pid %s",
            result.workspace_num,
            result.pid,
        )
        return False


__all__ = ["rollback_partial_launch_results"]
