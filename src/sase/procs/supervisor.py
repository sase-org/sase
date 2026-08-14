"""Detached command supervisor for :mod:`sase.procs.runner`."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from typing import IO, cast

from .logs import open_proc_log
from .models import TERMINAL_PROC_STATUSES
from .store import get_proc, update_proc

_KILL_GRACE_SECONDS = 1.0
_POLL_SECONDS = 0.05
_CHILD_ENV_VAR = "_SASE_PROC_CHILD_ENV_JSON"


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


def _run_supervisor(proc_id: str) -> int:
    """Own one recorded proc from child spawn through terminal status."""
    proc = get_proc(proc_id)
    if proc is None:
        return 2
    if proc.status in TERMINAL_PROC_STATUSES:
        return 0

    termination = _Termination()
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)

    status = "error"
    exit_code: int | None = None
    message = "supervisor exited without reporting"
    try:
        with open_proc_log(proc_id) as log:
            if termination.requested:
                status = "killed"
                message = "proc killed"
            else:
                child_env = _child_environment()
                child_env.update(
                    {
                        "SASE_PROC_ID": proc.proc_id,
                        "SASE_PROC_LOG_PATH": proc.log_path,
                        "SASE_PROC_SESSION_ID": proc.session_id or "",
                    }
                )
                try:
                    output = cast(IO[str], log)
                    child = subprocess.Popen(
                        proc.command,
                        cwd=proc.cwd,
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
                    running = update_proc(
                        proc_id,
                        status="running",
                        pid=os.getpid(),
                        pgid=child.pid,
                        started_at=_utc_timestamp(),
                    )
                    if (
                        running.proc is None
                        or running.proc.status in TERMINAL_PROC_STATUSES
                    ):
                        termination.request(signal.SIGTERM, None)
                    exit_code = termination.wait()
                    if termination.requested:
                        status = "killed"
                        message = "proc killed"
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
            message = "proc killed"
        else:
            status = "error"
            message = f"supervisor error: {_one_line(exc)}"
    finally:
        update_proc(
            proc_id,
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
        raise ValueError("proc child environment must contain string pairs")
    env.update(overlay)
    return env


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE proc.")
    parser.add_argument("--proc-id", required=True)
    return parser


def _main() -> int:
    return _run_supervisor(_parser().parse_args().proc_id)


if __name__ == "__main__":
    raise SystemExit(_main())
