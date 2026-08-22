"""Hardened detached supervisor for one proc-shell row."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sase.agent.env_hygiene import scrub_agent_identity_env, scrub_chop_context_env
from sase.logs.pipe import BoundedLogPipe

from .identity import supervisor_identity_token
from .logs import proc_log_max_bytes
from .models import (
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcSupervisorClaim,
)
from .runtime import (
    launch_barrier_timeout_seconds,
    proc_go_path,
    proc_request_sidecar_path,
    proc_started_path,
    read_json_object,
    write_json_atomic,
)
from .settlement import maybe_crash, settle_proc_shell
from .store import claim_proc_supervisor, get_proc, update_proc

_POLL_SECONDS = 0.05
_KILL_GRACE_SECONDS = 5.0
_TimeoutKind = Literal["total", "idle"]


class _Termination:
    """Forward stop/timeout signals to the command's process group."""

    def __init__(self) -> None:
        self.requested = False
        self.requested_signum: int | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self.kill_deadline: float | None = None

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True
        if self.requested_signum is None:
            self.requested_signum = _signum
        self._signal_child()

    def trigger_timeout(self) -> None:
        self._signal_child()

    def attach(self, child: subprocess.Popen[bytes]) -> None:
        self.child = child
        if self.requested:
            self._signal_child()

    def maybe_escalate(self) -> None:
        if (
            self.kill_deadline is not None
            and self.child is not None
            and self.child.poll() is None
            and time.monotonic() >= self.kill_deadline
        ):
            _signal_group(self.child.pid, signal.SIGKILL)
            self.kill_deadline = None

    def _signal_child(self) -> None:
        if self.child is not None and self.child.poll() is None:
            _signal_group(self.child.pid, signal.SIGTERM)
            self.kill_deadline = time.monotonic() + _KILL_GRACE_SECONDS

    def terminate_after_failure(self) -> None:
        if self.child is None or self.child.poll() is not None:
            return
        _signal_group(self.child.pid, signal.SIGTERM)
        try:
            self.child.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(self.child.pid, signal.SIGKILL)
            self.child.wait()


class _OutputActivity:
    """Track output arrival from the drain thread for idle-timeout checks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_chunk_at = time.monotonic()

    def append_bytes(self, _chunk: bytes) -> None:
        with self._lock:
            self._last_chunk_at = time.monotonic()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_chunk_at


def run_supervisor(proc_id: str, *, startup_signal: int | None = None) -> int:
    """Own one proc-shell from claim through terminal settlement."""
    termination = _Termination()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)
    if startup_signal is not None:
        termination.request(startup_signal, None)

    proc = get_proc(proc_id)
    if proc is None:
        return 2
    if proc.status in TERMINAL_PROC_STATUSES:
        return 0
    if startup_signal is not None:
        finished = settle_proc_shell(
            proc.proc_id,
            supervisor_id=proc.supervisor_id or supervisor_identity_token(os.getpid()),
            status="error",
            message="proc supervisor died without acknowledging startup; command was not run",
            termination_reason="launch-failure",
        )
        return 0 if finished.status == "success" else 1

    supervisor_id = supervisor_identity_token(os.getpid())
    if proc.status == "settling":
        owner = proc.supervisor_id or supervisor_id
        finished = settle_proc_shell(
            proc.proc_id,
            supervisor_id=owner,
            status="error",
            message=proc.message or "supervisor resumed settlement",
            termination_reason="supervisor-loss",
            exit_code=proc.exit_code,
        )
        return 0 if finished.status == "success" else 1

    status = "error"
    exit_code: int | None = None
    message = "supervisor exited without reporting"
    termination_reason = "supervisor-loss"
    output_pipe: BoundedLogPipe | None = None
    try:
        proc = _claim_supervisor(proc, supervisor_id)
        prepare_error = _prepare_xprompt_proc(proc, termination)
        if prepare_error is not None:
            message = prepare_error
            status = "killed" if termination.requested else "error"
            termination_reason = "stop" if termination.requested else "launch-failure"
            proc = get_proc(proc.proc_id) or proc
        activity = _OutputActivity()
        output_pipe = BoundedLogPipe(
            Path(proc.log_path),
            proc_log_max_bytes(),
            on_chunk=activity.append_bytes,
            close_drain_seconds=0.5,
        )
        _write_start_acknowledgement(proc, supervisor_id)
        maybe_crash("ack")
        barrier_error = _wait_for_launch_barrier(proc.proc_id, termination)
        if prepare_error is not None:
            _append_supervisor_line(output_pipe, message)
        elif barrier_error is not None:
            message = barrier_error
            status = "killed" if termination.requested else "error"
            termination_reason = "stop" if termination.requested else "launch-failure"
            _append_supervisor_line(output_pipe, message)
        elif termination.requested:
            message = "proc killed"
            status = "killed"
            termination_reason = "stop"
            _append_supervisor_line(output_pipe, message)
        else:
            proc = get_proc(proc.proc_id) or proc
            outcome = _run_command(proc, termination, activity, output_pipe)
            status = outcome["status"]
            exit_code = outcome["exit_code"]
            message = outcome["message"]
            termination_reason = outcome["termination_reason"]
    except BaseException as exc:
        termination.terminate_after_failure()
        if termination.requested:
            status = "killed"
            message = "proc killed"
            termination_reason = "stop"
        else:
            status = "error"
            message = f"supervisor error: {_one_line(exc)}"
            termination_reason = "supervisor-loss"
        _append_supervisor_line(output_pipe, message)
    finally:
        close_error = _close_output_pipe(output_pipe)
        if close_error is not None and status != "killed":
            status = "error"
            message = f"supervisor error: {_one_line(close_error)}"
            termination_reason = "supervisor-loss"
        settle_proc_shell(
            proc_id,
            supervisor_id=supervisor_id,
            status=status,
            message=message,
            termination_reason=termination_reason,
            exit_code=exit_code,
        )
    return 0 if status == "success" else 1


def _prepare_xprompt_proc(proc: Proc, termination: _Termination) -> str | None:
    if proc.origin != "xprompt-proc":
        return None
    from sase.agent.launch_proc_runtime import prepare_xprompt_proc_supervisor

    if termination.requested:
        return "proc killed"
    return prepare_xprompt_proc_supervisor(
        proc,
        cancelled=lambda: termination.requested,
    )


def _claim_supervisor(proc: Proc, supervisor_id: str) -> Proc:
    claimed = claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id=proc.proc_id,
            supervisor_id=supervisor_id,
            claimed_at=_utc_timestamp(),
            pid=os.getpid(),
            pgid=os.getpgid(0),
        )
    ).proc
    return claimed or proc


def _write_start_acknowledgement(proc: Proc, supervisor_id: str) -> None:
    pid = os.getpid()
    write_json_atomic(
        proc_started_path(proc.proc_id),
        {
            "pgid": os.getpgid(0),
            "pid": pid,
            "proc_id": proc.proc_id,
            "supervisor_id": supervisor_id,
            "timestamp": time.time(),
        },
    )


def _wait_for_launch_barrier(proc_id: str, termination: _Termination) -> str | None:
    marker_path = proc_go_path(proc_id)
    deadline = time.monotonic() + launch_barrier_timeout_seconds()
    while True:
        if termination.requested:
            return "proc killed"
        if marker_path.exists():
            return None
        if time.monotonic() >= deadline:
            timeout = _format_duration(launch_barrier_timeout_seconds())
            return (
                f"proc start barrier was not released within {timeout}; "
                "command was not run"
            )
        time.sleep(_POLL_SECONDS)


def _run_command(
    proc: Proc,
    termination: _Termination,
    activity: _OutputActivity,
    output_pipe: BoundedLogPipe,
) -> dict[str, Any]:
    request = read_json_object(proc_request_sidecar_path(proc.proc_id))
    overlay = request.get("env") if isinstance(request.get("env"), dict) else None
    argv = list(proc.argv or proc.command)
    cwd = str(request.get("cwd") or proc.cwd)
    try:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=_child_environment(proc, overlay),
            stdin=subprocess.DEVNULL,
            stdout=cast(Any, output_pipe),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            text=False,
        )
    except (OSError, ValueError) as exc:
        message = f"could not start command: {_one_line(exc)}"
        _append_supervisor_line(output_pipe, message)
        return {
            "exit_code": None,
            "message": message,
            "status": "error",
            "termination_reason": "launch-failure",
        }

    termination.attach(child)
    update_proc(proc.proc_id, pgid=child.pid)
    timeout_kind = _wait_for_child(
        child,
        termination,
        float(proc.timeout_seconds or 0),
        float(proc.idle_timeout_seconds or 0),
        activity,
    )
    exit_code = child.returncode
    if termination.requested:
        return {
            "exit_code": exit_code,
            "message": "proc killed",
            "status": "killed",
            "termination_reason": "stop",
        }
    if timeout_kind is not None:
        return {
            "exit_code": exit_code,
            "message": _timeout_message(
                timeout_kind,
                total_timeout_seconds=float(proc.timeout_seconds or 0),
                idle_timeout_seconds=float(proc.idle_timeout_seconds or 0),
            ),
            "status": "error",
            "termination_reason": f"{timeout_kind}-timeout",
        }
    if exit_code == 0:
        return {
            "exit_code": exit_code,
            "message": "completed successfully",
            "status": "success",
            "termination_reason": "success",
        }
    return {
        "exit_code": exit_code,
        "message": f"exited with code {exit_code}",
        "status": "error",
        "termination_reason": "error",
    }


def _wait_for_child(
    child: subprocess.Popen[bytes],
    termination: _Termination,
    timeout_seconds: float,
    idle_timeout_seconds: float,
    activity: _OutputActivity,
) -> _TimeoutKind | None:
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    timeout_kind: _TimeoutKind | None = None
    while True:
        if child.poll() is not None:
            return timeout_kind
        now = time.monotonic()
        if deadline is not None and timeout_kind is None and now >= deadline:
            timeout_kind = "total"
            termination.trigger_timeout()
        if (
            idle_timeout_seconds > 0
            and timeout_kind is None
            and activity.idle_seconds() >= idle_timeout_seconds
        ):
            timeout_kind = "idle"
            termination.trigger_timeout()
        termination.maybe_escalate()
        time.sleep(_POLL_SECONDS)


def _child_environment(proc: Proc, overlay: dict[str, Any] | None) -> dict[str, str]:
    if proc.origin == "xprompt-proc":
        env = {
            str(key): str(value)
            for key, value in (overlay or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        env["SASE_PROC_ID"] = proc.proc_id
        env["SASE_PROC_LOG_PATH"] = proc.log_path
        env.pop("SASE_AGENT", None)
        for key in list(env):
            if key.startswith("SASE_AGENT_"):
                env.pop(key, None)
        return env
    env = os.environ.copy()
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    env.pop("SASE_ARTIFACTS_DIR", None)
    if overlay is not None:
        for key, value in overlay.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = value
    env["SASE_PROC_ID"] = proc.proc_id
    env["SASE_PROC_LOG_PATH"] = proc.log_path
    env["SASE_PROC_SESSION_ID"] = proc.session_id or ""
    return env


def _close_output_pipe(output_pipe: BoundedLogPipe | None) -> BaseException | None:
    if output_pipe is None or output_pipe.closed:
        return None
    try:
        output_pipe.close()
    except BaseException as exc:
        return exc
    return None


def _append_supervisor_line(output_pipe: BoundedLogPipe | None, message: str) -> None:
    if output_pipe is None or output_pipe.closed:
        return
    try:
        output_pipe.write(f"{message.rstrip()}\n")
    except (OSError, ValueError):
        pass


def _timeout_message(
    timeout_kind: _TimeoutKind,
    *,
    total_timeout_seconds: float,
    idle_timeout_seconds: float,
) -> str:
    if timeout_kind == "idle":
        return f"no output for {_format_duration(idle_timeout_seconds)}"
    elapsed = _format_duration(total_timeout_seconds)
    return f"did not finish after {elapsed} of a {elapsed} budget"


def _format_duration(seconds: float) -> str:
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE proc-shell.")
    parser.add_argument("--proc-id", required=True)
    return parser


def _main() -> int:
    return run_supervisor(_parser().parse_args().proc_id)


if __name__ == "__main__":
    raise SystemExit(_main())
