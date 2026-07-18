"""Script-chop execution and live-run dedupe for the shared chop runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.time import get_timezone

from .chop_agents import build_chop_launch_env
from .chop_script_runner import discover_chop_script, stream_chop_script
from .config import AxeConfig, ChopConfig
from .state import (
    ChopRunEntry,
    ChopRunSource,
    chop_run_log_path,
    ensure_lumberjack_dirs,
    finish_chop_run,
    generate_chop_run_id,
    read_chop_run,
    read_chop_run_index,
    start_chop_run,
    update_chop_run_pid,
    write_chop_run,
)
from .chop_runner_context import build_oneshot_context
from .chop_runner_trace import NO_PYTHON_TRACEBACK, capture_traceback
from .chop_runner_types import ChopRunOutcome


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
            now = datetime.now()
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
    """Return the newest chop run entry if it is still in ``running`` state.

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
            finished_at_for_duration = datetime.now()
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


def run_script_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None,
    context_file: str | None,
    source: ChopRunSource,
    started_by: str | None,
    discover_chop_script_fn: Callable[
        [str, list[str]], Path | None
    ] = discover_chop_script,
    stream_chop_script_fn: Callable[..., Any] = stream_chop_script,
    build_context_fn: Callable[[str, AxeConfig], str] = build_oneshot_context,
    is_process_running_fn: Callable[[int], bool] = is_process_running,
) -> ChopRunOutcome:
    resolved_timeout = chop.timeout or chop_timeout_default
    live = active_script_chop_run(
        lumberjack_name,
        chop.name,
        pidless_stale_after_seconds=resolved_timeout,
        is_process_running_fn=is_process_running_fn,
    )
    if live is not None:
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="already_running",
            run_id=live.run_id,
        )

    started_at = datetime.now(get_timezone())
    run_id = generate_chop_run_id(started_at)

    script_name = chop.script_name
    script = discover_chop_script_fn(script_name, axe_config.chop_script_dirs)
    if script is None:
        error = RuntimeError(
            f"Chop script not found: {script_name} (chop: {chop.name})"
        )
        finished_at = datetime.now(get_timezone())
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        try:
            write_chop_run(
                ChopRunEntry(
                    run_id=run_id,
                    lumberjack_name=lumberjack_name,
                    chop_name=chop.name,
                    started_at=started_at.isoformat(),
                    finished_at=finished_at.isoformat(),
                    duration_ms=duration_ms,
                    status="missing_script",
                    error=str(error),
                    traceback=NO_PYTHON_TRACEBACK,
                    source=source,
                    started_by=started_by,
                )
            )
        except OSError:
            pass
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="missing_script",
            run_id=run_id,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
        )

    env = dict(chop.env)
    env.update(
        build_chop_launch_env(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            prompt=None,
        )
    )

    state_dir = ensure_lumberjack_dirs(lumberjack_name)
    if context_file is None:
        context_file = build_context_fn(lumberjack_name, axe_config)

    start_entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        source=source,
        started_by=started_by,
    )
    try:
        start_chop_run(start_entry)
    except OSError:
        pass

    log_path = chop_run_log_path(lumberjack_name, chop.name, run_id)

    def _record_pid(pid: int) -> None:
        try:
            update_chop_run_pid(lumberjack_name, chop.name, run_id, pid)
        except OSError:
            pass

    try:
        result = stream_chop_script_fn(
            script,
            context_file,
            log_path=log_path,
            timeout=resolved_timeout,
            env=env,
            cwd=str(state_dir),
            on_pid=_record_pid,
        )
    except Exception as e:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="failure",
            exit_code=None,
            error=e,
            tb=tb,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="failure",
            run_id=run_id,
            error=e,
            traceback=tb,
        )

    if result.timed_out:
        error = RuntimeError(f"timed out after {resolved_timeout}s")
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="timeout",
            exit_code=None,
            error=error,
            tb=NO_PYTHON_TRACEBACK,
            output_bytes=result.output_bytes,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="timeout",
            run_id=run_id,
            output_bytes=result.output_bytes,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
        )

    if result.returncode == 0:
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="success",
            exit_code=0,
            output_bytes=result.output_bytes,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="success",
            run_id=run_id,
            exit_code=0,
            output_bytes=result.output_bytes,
        )

    error = RuntimeError(f"exit code {result.returncode}")
    _finalize(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        run_id=run_id,
        started_at=started_at,
        status="failure",
        exit_code=result.returncode,
        error=error,
        tb=NO_PYTHON_TRACEBACK,
        output_bytes=result.output_bytes,
    )
    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        status="failure",
        run_id=run_id,
        exit_code=result.returncode,
        output_bytes=result.output_bytes,
        error=error,
        traceback=NO_PYTHON_TRACEBACK,
    )


def _finalize(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    started_at: datetime,
    status: str,
    exit_code: int | None = None,
    error: Exception | None = None,
    tb: str | None = None,
    output_bytes: int | None = None,
) -> None:
    """Stamp terminal state onto a previously-opened streaming run entry."""
    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    try:
        finish_chop_run(
            lumberjack_name,
            chop_name,
            run_id,
            status=status,  # type: ignore[arg-type]
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            exit_code=exit_code,
            error=str(error) if error is not None else None,
            traceback=tb,
            output_bytes=output_bytes,
        )
    except OSError:
        pass


_active_script_chop_run = active_script_chop_run
_run_script_chop_once = run_script_chop_once
