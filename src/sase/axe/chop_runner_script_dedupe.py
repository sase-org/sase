"""Live-run dedupe and stale-run recovery for script-backed chops."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sase.ace.hooks.processes import is_process_running
from sase.core.time import get_timezone

from .chop_runner_trace import NO_PYTHON_TRACEBACK
from .state import (
    ChopRunEntry,
    finish_chop_run,
    read_chop_run,
    read_chop_run_index,
)


PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS = 300


def _pidless_script_chop_stale_after_seconds(resolved_timeout: int | None) -> int:
    """Return the grace window before PID-less running script rows are stale."""
    if resolved_timeout is not None and resolved_timeout > 0:
        return resolved_timeout
    return PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS


def _script_chop_run_age_seconds(entry: ChopRunEntry, now: datetime) -> float | None:
    """Return run age in seconds, or None when ``started_at`` is unreadable."""
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        return None
    if started_at.tzinfo is None:
        if now.tzinfo is not None:
            now = now.astimezone(get_timezone()).replace(tzinfo=None)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=started_at.tzinfo)
    else:
        now = now.astimezone(started_at.tzinfo)
    return max(0.0, (now - started_at).total_seconds())


def active_script_chop_run(
    lumberjack_name: str,
    chop_name: str,
    *,
    pidless_stale_after_seconds: int | None = None,
    is_process_running_fn: Callable[[int], bool] = is_process_running,
) -> ChopRunEntry | None:
    """Return the newest chop run entry if its script or action is active.

    Only the head of the index is inspected: pruning keeps active runs at the
    front, and a finalized newest entry means there is no live run to dedupe
    against. A ``running`` row with a stored PID is trusted only while that
    process is still alive; dead-PID rows are finalized so the next scheduled
    run can recover. PID-less rows are kept active only for a grace window so
    a crash before PID recording cannot block future runs indefinitely.
    """
    index = read_chop_run_index(lumberjack_name, chop_name)
    if not index:
        return None
    head_id = index[0]
    head = read_chop_run(lumberjack_name, chop_name, head_id)
    if head is None:
        return None
    if head.status == "launched":
        return head
    if head.status != "running":
        return None

    if head.pid is not None and head.pid > 0:
        if not is_process_running_fn(head.pid):
            _finalize_stale_script_chop_run(
                head,
                reason=f"stale running chop process exited: pid {head.pid}",
            )
            return None
        return head

    stale_after = _pidless_script_chop_stale_after_seconds(pidless_stale_after_seconds)
    age_seconds = _script_chop_run_age_seconds(head, datetime.now(get_timezone()))
    if age_seconds is None or age_seconds >= stale_after:
        _finalize_stale_script_chop_run(
            head,
            reason=(
                "stale running chop never recorded a pid after "
                f"{stale_after}s grace window"
            ),
        )
        return None

    return head


def _finalize_stale_script_chop_run(entry: ChopRunEntry, *, reason: str) -> None:
    """Mark a running script-chop entry stale after dedupe proves it stale."""
    finished_at = datetime.now(get_timezone())
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        duration_ms = 0
    else:
        if started_at.tzinfo is None:
            finished_at_for_duration = finished_at.replace(tzinfo=None)
        else:
            finished_at_for_duration = finished_at.astimezone(started_at.tzinfo)
        duration_ms = max(
            0,
            int((finished_at_for_duration - started_at).total_seconds() * 1000),
        )

    try:
        finish_chop_run(
            entry.lumberjack_name,
            entry.chop_name,
            entry.run_id,
            status="failure",
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            exit_code=None,
            error=reason,
            traceback=NO_PYTHON_TRACEBACK,
        )
    except OSError:
        pass


__all__ = [
    "PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS",
    "active_script_chop_run",
]
