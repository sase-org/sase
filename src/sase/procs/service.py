"""Typed proc-shell service over the Rust lifecycle and detached supervisor."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .identity import (
    supervisor_from_previous_boot,
    supervisor_identity_token,
    supervisor_is_alive,
)
from .ids import new_proc_id
from .logs import proc_log_path
from .models import (
    ACTIVE_PROC_STATUSES,
    PROC_LIFECYCLE_PROC_SHELL,
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcReserve,
    ProcStopRequest,
)
from .request import (
    ProcSubmitRequest,
    proc_request_fingerprint,
    request_sidecar_payload,
)
from .runtime import proc_request_sidecar_path, write_json_atomic
from .settlement import is_proc_shell_row, settle_proc_shell
from .spawn import (
    DetachedSupervisor,
    SupervisorSpawnError,
    spawn_detached_supervisor,
    terminate_supervisor,
    wait_for_start_acknowledgement,
    write_launch_barrier,
)
from .store import get_proc, read_procs, request_proc_stop, reserve_proc

_UNCLAIMED_GRACE_SECONDS = 60.0
_STOP_WAIT_SECONDS = 15.0
_LAUNCH_SETTLE_SECONDS = 8.0
_POLL_SECONDS = 0.05

SUPERVISOR_LOSS_MESSAGE = "supervisor exited without reporting"
REBOOT_LOSS_MESSAGE = (
    "proc supervisor belongs to a previous boot; command outcome is unknown"
)


class ProcSubmitError(RuntimeError):
    """A proc could not be validated or its supervisor could not be started."""


class ProcControlError(RuntimeError):
    """A durable proc could not be found or controlled."""


def submit_proc_request(request: ProcSubmitRequest) -> Proc:
    """Reserve a proc-shell and launch its detached supervisor."""
    argv = _validated_argv(request.argv)
    cwd = str(_validated_cwd(request.cwd))
    proc_id = new_proc_id()
    log_path = str(request.log_path or proc_log_path(proc_id))
    fingerprint = proc_request_fingerprint(request, proc_id=proc_id, cwd=cwd, argv=argv)
    reserved_by = request.reserved_by or _default_reserved_by()
    created_at = _utc_timestamp()
    try:
        outcome = reserve_proc(
            ProcReserve(
                proc_id=proc_id,
                label=request.label,
                kind=request.kind,
                argv=argv,
                cwd=cwd,
                project=request.project,
                workspace_num=request.workspace_num,
                session_id=request.session_id,
                session_label=request.session_label,
                origin=request.origin,
                cl_name=request.cl_name,
                tags=sorted(set(request.tags)),
                created_at=created_at,
                log_path=log_path,
                log_owner=request.log_owner,
                shell_name=request.shell_name,
                shell_kind=request.shell_kind,
                concurrency_keys=list(request.concurrency_keys),
                request_fingerprint=fingerprint,
                reserved_by=reserved_by,
                timeout_seconds=request.timeout_seconds,
                idle_timeout_seconds=request.idle_timeout_seconds,
            )
        )
    except Exception as exc:
        raise ProcSubmitError(f"could not record proc: {_one_line(exc)}") from exc

    if outcome.replayed:
        return outcome.proc

    write_json_atomic(
        proc_request_sidecar_path(outcome.proc.proc_id),
        request_sidecar_payload(
            request,
            proc_id=outcome.proc.proc_id,
            argv=argv,
            cwd=cwd,
            log_path=log_path,
            fingerprint=fingerprint,
        ),
    )
    return _launch_reserved(outcome.proc, fingerprint=fingerprint)


def stop_proc_shell(proc: Proc, *, requested_by: str | None = None) -> Proc:
    """Record stop intent, signal the supervisor, and wait for settlement."""
    if proc.status in TERMINAL_PROC_STATUSES:
        return proc
    request_proc_stop(
        ProcStopRequest(
            proc_id=proc.proc_id,
            requested_by=requested_by or _default_reserved_by(),
            requested_at=_utc_timestamp(),
            reason="stop",
        )
    )
    current = get_proc(proc.proc_id) or proc
    if supervisor_from_previous_boot(current.supervisor_id):
        return _reconcile_proc_shell(current)
    if not supervisor_is_alive(current.pid, current.supervisor_id):
        return _reconcile_proc_shell(current)
    assert current.pid is not None
    try:
        os.kill(current.pid, signal.SIGTERM)
    except ProcessLookupError:
        return _reconcile_proc_shell(current)
    except PermissionError as exc:
        raise ProcControlError(
            f"permission denied killing proc {current.proc_id}"
        ) from exc
    finished = _wait_for_terminal(current.proc_id, timeout=_STOP_WAIT_SECONDS)
    if finished is not None:
        return finished
    terminate_supervisor(
        DetachedSupervisor(pid=current.pid, identity=current.supervisor_id)
    )
    finished = _wait_for_terminal(current.proc_id, timeout=2.0)
    return finished or _reconcile_proc_shell(get_proc(current.proc_id) or current)


def reconcile_proc_shells() -> list[Proc]:
    """Resume or finish proc-shell rows whose supervisor is gone."""
    reconciled: list[Proc] = []
    for proc in read_procs(status=ACTIVE_PROC_STATUSES):
        if not is_proc_shell_row(proc) or not _should_reconcile(proc):
            continue
        current = get_proc(proc.proc_id)
        if current is None or current.status not in ACTIVE_PROC_STATUSES:
            continue
        finished = _reconcile_proc_shell(current)
        if finished.status in TERMINAL_PROC_STATUSES:
            reconciled.append(finished)
    return reconciled


def _reconcile_proc_shell(proc: Proc) -> Proc:
    """Settle one active proc-shell after loss, reboot, or a crash boundary."""
    current = get_proc(proc.proc_id) or proc
    if current.status in TERMINAL_PROC_STATUSES:
        return current
    reboot = supervisor_from_previous_boot(current.supervisor_id)
    if not reboot and current.pgid is not None:
        _signal_leftover_group(current.pgid)
    if reboot:
        reason = "reboot"
        message = REBOOT_LOSS_MESSAGE
    elif current.stop_requested_at:
        reason = "stop"
        message = "proc killed"
    elif current.status == "pending" and current.supervisor_id is None:
        reason = "launch-failure"
        message = SUPERVISOR_LOSS_MESSAGE
    else:
        reason = "supervisor-loss"
        message = SUPERVISOR_LOSS_MESSAGE
    status = "killed" if reason == "stop" else "error"
    owner = (
        current.supervisor_id or f"reconcile-{supervisor_identity_token(os.getpid())}"
    )
    return settle_proc_shell(
        current.proc_id,
        supervisor_id=owner,
        status=status,
        message=message,
        termination_reason=reason,
        exit_code=current.exit_code,
    )


def _launch_reserved(proc: Proc, *, fingerprint: str) -> Proc:
    try:
        supervisor = spawn_detached_supervisor(proc.proc_id)
    except SupervisorSpawnError as exc:
        message = f"could not start proc supervisor: {_one_line(exc)}"
        settle_proc_shell(
            proc.proc_id,
            supervisor_id=_starter_supervisor_id(),
            status="error",
            message=message,
            termination_reason="launch-failure",
        )
        raise ProcSubmitError(message) from exc

    ack_error = wait_for_start_acknowledgement(proc.proc_id, supervisor)
    if ack_error is not None:
        terminate_supervisor(supervisor)
        _wait_for_terminal(proc.proc_id, timeout=_LAUNCH_SETTLE_SECONDS)
        current = get_proc(proc.proc_id) or proc
        if current.status not in TERMINAL_PROC_STATUSES:
            settle_proc_shell(
                proc.proc_id,
                supervisor_id=current.supervisor_id or _starter_supervisor_id(),
                status="error",
                message=ack_error,
                termination_reason="launch-failure",
            )
        raise ProcSubmitError(ack_error)

    try:
        write_launch_barrier(proc.proc_id, request_fingerprint=fingerprint)
    except OSError as exc:
        terminate_supervisor(supervisor)
        message = f"could not release proc launch barrier: {_one_line(exc)}"
        settle_proc_shell(
            proc.proc_id,
            supervisor_id=_starter_supervisor_id(),
            status="error",
            message=message,
            termination_reason="launch-failure",
        )
        raise ProcSubmitError(message) from exc

    return get_proc(proc.proc_id) or proc


def _should_reconcile(proc: Proc) -> bool:
    if proc.lifecycle != PROC_LIFECYCLE_PROC_SHELL:
        return False
    if proc.status == "settling":
        return not supervisor_is_alive(proc.pid, proc.supervisor_id)
    if supervisor_from_previous_boot(proc.supervisor_id):
        return True
    if proc.pid is not None:
        return not supervisor_is_alive(proc.pid, proc.supervisor_id)
    return _age_seconds(proc.created_at) >= _UNCLAIMED_GRACE_SECONDS


def _wait_for_terminal(proc_id: str, *, timeout: float) -> Proc | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = get_proc(proc_id)
        if current is not None and current.status in TERMINAL_PROC_STATUSES:
            return current
        time.sleep(_POLL_SECONDS)
    current = get_proc(proc_id)
    if current is not None and current.status in TERMINAL_PROC_STATUSES:
        return current
    return None


def _signal_leftover_group(pgid: int) -> None:
    if pgid <= 0 or pgid == os.getpgrp():
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            break
        time.sleep(_POLL_SECONDS)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _validated_argv(argv: Sequence[str]) -> list[str]:
    command = [str(part) for part in argv]
    if not command or not command[0]:
        raise ProcSubmitError("proc command must contain a non-empty argv")
    return command


def _validated_cwd(cwd: str | Path) -> Path:
    path = Path(cwd).expanduser()
    if not path.is_dir():
        raise ProcSubmitError(f"proc cwd is not an existing directory: {path}")
    return path.resolve()


def _default_reserved_by() -> str:
    return (
        os.environ.get("SASE_AGENT")
        or os.environ.get("SASE_AGENT_NAME")
        or f"proc-service:{os.getpid()}"
    )


def _starter_supervisor_id() -> str:
    return f"starter-{supervisor_identity_token(os.getpid())}"


def _age_seconds(timestamp: str) -> float:
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds()


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


__all__ = [
    "ProcControlError",
    "ProcSubmitError",
    "REBOOT_LOSS_MESSAGE",
    "SUPERVISOR_LOSS_MESSAGE",
    "reconcile_proc_shells",
    "stop_proc_shell",
    "submit_proc_request",
]
