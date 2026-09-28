"""Interactive user-kill requests and background escalation."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from sase.agent._user_kill_intent import (
    record_user_kill_result,
    target_identity_is_verified,
    write_user_kill_intent,
)
from sase.agent._user_kill_tree import terminate_agent_processes
from sase.agent._user_kill_types import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    POLL_INTERVAL_SECONDS,
    AgentTerminationResult,
    Killpg,
    SleepFn,
    TimeFn,
)
from sase.agent.process_tree import (
    descendants_of,
    process_is_running,
    read_process_table,
)

_IMMEDIATE_ESCALATION_GRACE_SECONDS = 0.5


def _signal_immediately(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    marker_path: str | None,
    killpg: Killpg,
) -> AgentTerminationResult:
    """Send the interactive stage's single SIGTERM to the agent's group."""
    pgid = pid
    if not target_identity_is_verified(pid, artifacts_dir=artifacts_dir):
        result = AgentTerminationResult(
            True, "identity_mismatch", pid, pgid, marker_path=marker_path
        )
        record_user_kill_result(marker_path, result)
        return result
    try:
        killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        result = _signal_non_leader(pid, marker_path=marker_path)
        if result.status != "killed":
            record_user_kill_result(marker_path, result)
            return result
    except PermissionError as exc:
        result = AgentTerminationResult(
            False,
            "permission_denied",
            pid,
            pgid,
            marker_path=marker_path,
            error=str(exc) or "permission denied",
        )
        record_user_kill_result(marker_path, result)
        return result

    initial = AgentTerminationResult(True, "killed", pid, pgid, marker_path=marker_path)
    record_user_kill_result(marker_path, initial)
    return initial


def _signal_non_leader(pid: int, *, marker_path: str | None) -> AgentTerminationResult:
    """SIGTERM a pid that has no process group of its own, plus its tree.

    ``killpg`` on such a pid raises ``ProcessLookupError`` even though the
    process is alive, so the pid is re-checked before the group failure is
    believed.
    """
    if not process_is_running(pid):
        return AgentTerminationResult(
            True, "already_stopped", pid, pid, marker_path=marker_path
        )
    tree = [pid, *descendants_of([pid], read_process_table())]
    for target in tree:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            if target == pid:
                return AgentTerminationResult(
                    False,
                    "permission_denied",
                    pid,
                    pid,
                    marker_path=marker_path,
                    error=str(exc) or "permission denied",
                )
    return AgentTerminationResult(True, "killed", pid, pid, marker_path=marker_path)


def escalate_user_kill_in_background(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    marker_path: str | Path | None = None,
    grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
) -> threading.Thread:
    """Run :func:`terminate_agent_processes` on a daemon thread.

    The thread dies with its process, so it is only a fallback for callers that
    could not hand termination to a durable proc.
    """
    thread = threading.Thread(
        target=terminate_agent_processes,
        args=(pid,),
        kwargs={
            "artifacts_dir": artifacts_dir,
            "grace_seconds": grace_seconds,
            "marker_path": marker_path,
        },
        name=f"sase-user-kill-{pid}",
        daemon=True,
    )
    thread.start()
    return thread


def request_user_kill(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    source: str,
    reason: str | None = None,
    wait: bool = True,
    background: bool = False,
    grace_seconds: float | None = None,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    killpg: Killpg = os.killpg,
    sleep_fn: SleepFn = time.sleep,
    monotonic_fn: TimeFn = time.monotonic,
) -> AgentTerminationResult:
    """Write user-kill intent, then terminate the agent.

    With ``wait=True`` this runs the full verified termination and blocks
    until the process set is dead or *grace_seconds* plus the post-kill window
    have elapsed. With ``wait=False`` it only sends the immediate SIGTERM; add
    ``background=True`` to also escalate on a daemon thread. Neither
    ``wait=False`` form verifies anything, so callers must hand the rest to a
    durable stage.
    """
    marker_path = write_user_kill_intent(
        artifacts_dir,
        pid=pid,
        source=source,
        reason=reason,
    )
    if wait:
        return terminate_agent_processes(
            pid,
            artifacts_dir=artifacts_dir,
            grace_seconds=(
                DEFAULT_TERMINATE_GRACE_SECONDS
                if grace_seconds is None
                else grace_seconds
            ),
            poll_interval=poll_interval,
            marker_path=marker_path,
            killpg=killpg,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
        )
    result = _signal_immediately(
        pid,
        artifacts_dir=artifacts_dir,
        marker_path=str(marker_path) if marker_path is not None else None,
        killpg=killpg,
    )
    if background and result.success and result.status == "killed":
        escalate_user_kill_in_background(
            pid,
            artifacts_dir=artifacts_dir,
            marker_path=marker_path,
            grace_seconds=(
                _IMMEDIATE_ESCALATION_GRACE_SECONDS
                if grace_seconds is None
                else grace_seconds
            ),
        )
    return result


__all__ = [
    "escalate_user_kill_in_background",
    "request_user_kill",
]
