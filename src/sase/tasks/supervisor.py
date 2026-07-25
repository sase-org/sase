"""Detached command supervisor for :mod:`sase.tasks.runner`."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from typing import IO, cast

from .logs import open_task_log
from .models import TERMINAL_TASK_STATUSES
from .store import get_task, update_task

_KILL_GRACE_SECONDS = 1.0
_POLL_SECONDS = 0.05
_CHILD_ENV_VAR = "_SASE_TASK_CHILD_ENV_JSON"


class _Termination:
    """Signal state shared by the handlers and child wait loop."""

    def __init__(self) -> None:
        self.requested = False
        self.child: subprocess.Popen[str] | None = None
        self.deadline: float | None = None

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True
        if self.child is not None and self.child.poll() is None:
            _signal_group(self.child.pid, signal.SIGTERM)
            self.deadline = time.monotonic() + _KILL_GRACE_SECONDS

    def attach(self, child: subprocess.Popen[str]) -> None:
        self.child = child
        if self.requested:
            self.request(signal.SIGTERM, None)

    def wait(self) -> int:
        assert self.child is not None
        while True:
            returncode = self.child.poll()
            if returncode is not None:
                return returncode
            if (
                self.requested
                and self.deadline is not None
                and time.monotonic() >= self.deadline
            ):
                _signal_group(self.child.pid, signal.SIGKILL)
                self.deadline = None
            time.sleep(_POLL_SECONDS)

    def terminate_after_failure(self) -> None:
        if self.child is None or self.child.poll() is not None:
            return
        _signal_group(self.child.pid, signal.SIGTERM)
        try:
            self.child.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(self.child.pid, signal.SIGKILL)
            self.child.wait()


def _run_supervisor(task_id: str) -> int:
    """Own one recorded task from child spawn through terminal status."""
    task = get_task(task_id)
    if task is None:
        return 2
    if task.status in TERMINAL_TASK_STATUSES:
        return 0

    termination = _Termination()
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)

    status = "error"
    exit_code: int | None = None
    message = "supervisor exited without reporting"
    try:
        with open_task_log(task_id) as log:
            if termination.requested:
                status = "killed"
                message = "task killed"
            else:
                child_env = _child_environment()
                child_env.update(
                    {
                        "SASE_TASK_ID": task.task_id,
                        "SASE_TASK_LOG_PATH": task.log_path,
                        "SASE_TASK_SESSION_ID": task.session_id or "",
                    }
                )
                try:
                    output = cast(IO[str], log)
                    child = subprocess.Popen(
                        task.command,
                        cwd=task.cwd,
                        env=child_env,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        close_fds=True,
                        text=True,
                    )
                except (OSError, ValueError) as exc:
                    message = f"could not start command: {_one_line(exc)}"
                    log.write(f"{message}\n")
                else:
                    termination.attach(child)
                    running = update_task(
                        task_id,
                        status="running",
                        pid=os.getpid(),
                        pgid=child.pid,
                        started_at=_utc_timestamp(),
                    )
                    if (
                        running.task is None
                        or running.task.status in TERMINAL_TASK_STATUSES
                    ):
                        termination.request(signal.SIGTERM, None)
                    exit_code = termination.wait()
                    if termination.requested:
                        status = "killed"
                        message = "task killed"
                    elif exit_code == 0:
                        status = "success"
                        message = "completed successfully"
                    else:
                        status = "error"
                        message = f"exited with code {exit_code}"
    except BaseException as exc:
        termination.terminate_after_failure()
        if termination.requested:
            status = "killed"
            message = "task killed"
        else:
            status = "error"
            message = f"supervisor error: {_one_line(exc)}"
    finally:
        update_task(
            task_id,
            status=status,
            exit_code=exit_code,
            message=message,
            finished_at=_utc_timestamp(),
        )
    return 0 if status == "success" else 1


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _child_environment() -> dict[str, str]:
    env = os.environ.copy()
    raw_overlay = env.pop(_CHILD_ENV_VAR, None)
    if raw_overlay is None:
        return env
    overlay = json.loads(raw_overlay)
    if not isinstance(overlay, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in overlay.items()
    ):
        raise ValueError("task child environment must contain string pairs")
    env.update(overlay)
    return env


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE task.")
    parser.add_argument("--task-id", required=True)
    return parser


def _main() -> int:
    return _run_supervisor(_parser().parse_args().task_id)


if __name__ == "__main__":
    raise SystemExit(_main())
