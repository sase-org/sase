"""Submission and control APIs for detached background tasks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sase.ace.hooks.processes import is_process_running

from .ids import new_task_id
from .logs import task_log_path
from .models import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    BackgroundTask,
)
from .store import append_task, get_task, read_tasks, update_task

LineCallback = Callable[[str], None]

_INITIAL_POLL_SECONDS = 0.05
_MAX_POLL_SECONDS = 0.5
_CHILD_ENV_VAR = "_SASE_TASK_CHILD_ENV_JSON"

# How long a command row may sit without a supervisor pid before
# reconciliation treats it as a submit that died before it spawned.
_UNCLAIMED_GRACE_SECONDS = 60.0


class TaskSubmitError(RuntimeError):
    """A task could not be validated or its supervisor could not be started."""


class TaskControlError(RuntimeError):
    """A durable task could not be found or controlled."""


def submit_task(
    argv: Sequence[str],
    *,
    label: str,
    cwd: str | Path,
    session_id: str | None = None,
    project: str | None = None,
    workspace_num: int | None = None,
    tags: Sequence[str] = (),
    origin: str = "api",
    cl_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BackgroundTask:
    """Record and detach a command task under the task supervisor."""
    command = _validated_argv(argv)
    resolved_cwd = _validated_cwd(cwd)
    task_id = new_task_id()
    task = BackgroundTask(
        task_id=task_id,
        label=label,
        kind="command",
        status="pending",
        command=command,
        cwd=str(resolved_cwd),
        project=project,
        workspace_num=workspace_num,
        session_id=session_id,
        session_label=_session_label(session_id),
        origin=origin,
        cl_name=cl_name,
        tags=sorted(set(tags)),
        created_at=_utc_timestamp(),
        log_path=str(task_log_path(task_id)),
    )
    try:
        append_task(task)
    except Exception as exc:
        raise TaskSubmitError(f"could not record task: {_one_line(exc)}") from exc

    supervisor_env = os.environ.copy()
    if env is not None:
        supervisor_env[_CHILD_ENV_VAR] = json.dumps(dict(env))
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.tasks.supervisor",
                "--task-id",
                task_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=supervisor_env,
        )
    except (OSError, ValueError) as exc:
        message = f"could not start task supervisor: {_one_line(exc)}"
        update_task(
            task_id,
            status="error",
            message=message,
            finished_at=_utc_timestamp(),
        )
        raise TaskSubmitError(message) from exc

    outcome = update_task(task_id, pid=process.pid)
    return outcome.task or task


def wait_for_task(
    task_id: str,
    *,
    timeout: float | None = None,
    on_line: LineCallback | None = None,
) -> BackgroundTask:
    """Wait for a task, streaming newly retained log lines through ``on_line``."""
    started = time.monotonic()
    delay = _INITIAL_POLL_SECONDS
    seen_log = ""
    buffered = ""
    while True:
        task = get_task(task_id)
        if task is None:
            raise TaskControlError(f"no task with id {task_id!r}")

        current_log = _read_retained_log(Path(task.log_path))
        new_text = _new_log_text(seen_log, current_log)
        seen_log = current_log
        if on_line is not None:
            buffered = _emit_complete_lines(buffered + new_text, on_line)

        if task.status in TERMINAL_TASK_STATUSES:
            if on_line is not None and buffered:
                on_line(buffered.rstrip("\r"))
            return task
        if timeout is not None and time.monotonic() - started >= timeout:
            raise TimeoutError(f"timed out waiting for task {task_id}")
        time.sleep(delay)
        delay = min(delay * 1.5, _MAX_POLL_SECONDS)


def kill_task(task_id: str) -> BackgroundTask:
    """Terminate a task's process group and durably mark it killed."""
    task = get_task(task_id)
    if task is None:
        raise TaskControlError(f"no task with id {task_id!r}")
    if task.status in TERMINAL_TASK_STATUSES:
        return task

    errors: list[OSError] = []
    if task.pid is not None:
        _signal_target(os.kill, task.pid, errors)
    if task.pgid is not None:
        _signal_target(os.killpg, task.pgid, errors)
    if errors:
        error = errors[0]
        if isinstance(error, PermissionError):
            raise TaskControlError(
                f"permission denied killing task {task_id}"
            ) from error
        raise TaskControlError(f"could not kill task {task_id}: {error}") from error

    outcome = update_task(
        task_id,
        status="killed",
        message="task killed",
        finished_at=_utc_timestamp(),
    )
    if outcome.task is None:
        raise TaskControlError(f"task {task_id!r} disappeared before it was killed")
    return outcome.task


def reconcile_running_tasks() -> list[BackgroundTask]:
    """Mark active rows whose supervisor died without terminalizing them."""
    reconciled: list[BackgroundTask] = []
    for task in read_tasks(status=ACTIVE_TASK_STATUSES):
        if not _is_orphaned(task):
            continue
        current = get_task(task.task_id)
        if current is None or current.status not in ACTIVE_TASK_STATUSES:
            continue
        outcome = update_task(
            task.task_id,
            status="error",
            message="supervisor exited without reporting",
            finished_at=_utc_timestamp(),
        )
        if outcome.task is not None:
            reconciled.append(outcome.task)
    return reconciled


def _is_orphaned(task: BackgroundTask) -> bool:
    """Return whether an active row's owner is gone without a terminal write."""
    if task.pid is not None:
        return not is_process_running(task.pid)
    # No supervisor pid yet. ``submit_task`` stamps one within milliseconds of
    # appending the row, and mirrored in-TUI tasks are owned by their own
    # process, so only a stale command row is a genuine ghost: reconciling a
    # just-submitted row would race its supervisor to a terminal status the
    # store then refuses to move off.
    if task.kind != "command":
        return False
    return _age_seconds(task.created_at) >= _UNCLAIMED_GRACE_SECONDS


def _age_seconds(timestamp: str) -> float:
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds()


def _validated_argv(argv: Sequence[str]) -> list[str]:
    command = [str(part) for part in argv]
    if not command or not command[0]:
        raise TaskSubmitError("task command must contain a non-empty argv")
    return command


def _validated_cwd(cwd: str | Path) -> Path:
    path = Path(cwd).expanduser()
    if not path.is_dir():
        raise TaskSubmitError(f"task cwd is not an existing directory: {path}")
    return path.resolve()


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _session_label(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    try:
        from sase.sessions import live_sessions, session_display_label

        identity = next(
            (item for item in live_sessions() if item.session_id == session_id),
            None,
        )
        return session_display_label(identity) if identity is not None else None
    except Exception:
        return None


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


def _read_retained_log(path: Path) -> str:
    chunks: list[str] = []
    for candidate in (path.with_name(f"{path.name}.1"), path):
        try:
            chunks.append(candidate.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "".join(chunks)


def _new_log_text(previous: str, current: str) -> str:
    if current.startswith(previous):
        return current[len(previous) :]
    if previous.endswith(current):
        return ""
    anchor = previous[-4096:]
    if anchor:
        offset = current.find(anchor)
        if offset >= 0:
            return current[offset + len(anchor) :]
    return current


def _emit_complete_lines(text: str, on_line: LineCallback) -> str:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        pending = lines.pop()
    else:
        pending = ""
    for line in lines:
        on_line(line.rstrip("\r\n"))
    return pending


def _signal_target(
    send: Callable[[int, int], None],
    target: int,
    errors: list[OSError],
) -> None:
    try:
        send(target, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        errors.append(exc)


__all__ = [
    "TaskControlError",
    "TaskSubmitError",
    "kill_task",
    "reconcile_running_tasks",
    "submit_task",
    "wait_for_task",
]
