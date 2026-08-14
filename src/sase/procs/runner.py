"""Submission and control APIs for detached procs."""

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

from .ids import new_proc_id
from .logs import proc_log_path
from .models import (
    ACTIVE_PROC_STATUSES,
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    TERMINAL_PROC_STATUSES,
    TUI_PROC_KIND,
    Proc,
)
from .store import append_proc, get_proc, read_procs, update_proc

LineCallback = Callable[[str], None]

_INITIAL_POLL_SECONDS = 0.05
_MAX_POLL_SECONDS = 0.5
_CHILD_ENV_VAR = "_SASE_PROC_CHILD_ENV_JSON"

# How long a supervisor-owned row may sit without a supervisor pid before
# reconciliation treats it as a submit that died before it spawned.
_UNCLAIMED_GRACE_SECONDS = 60.0

# Kinds whose rows are driven by ``sase.procs.supervisor`` rather than by the
# process that recorded them.
_SUPERVISOR_OWNED_KINDS = frozenset({COMMAND_PROC_KIND, DETACHED_PROC_KIND})


class ProcSubmitError(RuntimeError):
    """A proc could not be validated or its supervisor could not be started."""


class ProcControlError(RuntimeError):
    """A durable proc could not be found or controlled."""


def submit_proc(
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
) -> Proc:
    """Record and detach a command proc under the proc supervisor."""
    return _submit_supervised_proc(
        argv,
        kind=COMMAND_PROC_KIND,
        label=label,
        cwd=cwd,
        session_id=session_id,
        project=project,
        workspace_num=workspace_num,
        tags=tags,
        origin=origin,
        cl_name=cl_name,
        env=env,
    )


def submit_detached_proc(
    argv: Sequence[str],
    *,
    label: str,
    cwd: str | Path,
    origin: str,
    project: str | None = None,
    workspace_num: int | None = None,
    tags: Sequence[str] = (),
    cl_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Proc:
    """Record and detach a proc that no interactive session owns.

    A detached row carries no ``session_id``, so every surface keeps it in
    scope no matter which session — if any — submitted it. ``origin`` is the
    only record of where the work came from and is therefore required.
    """
    return _submit_supervised_proc(
        argv,
        kind=DETACHED_PROC_KIND,
        label=label,
        cwd=cwd,
        session_id=None,
        project=project,
        workspace_num=workspace_num,
        tags=tags,
        origin=origin,
        cl_name=cl_name,
        env=env,
    )


def _submit_supervised_proc(
    argv: Sequence[str],
    *,
    kind: str,
    label: str,
    cwd: str | Path,
    session_id: str | None,
    project: str | None,
    workspace_num: int | None,
    tags: Sequence[str],
    origin: str,
    cl_name: str | None,
    env: Mapping[str, str] | None,
) -> Proc:
    """Record a row, then spawn the supervisor that owns it."""
    command = _validated_argv(argv)
    resolved_cwd = _validated_cwd(cwd)
    proc_id = new_proc_id()
    proc = Proc(
        proc_id=proc_id,
        label=label,
        kind=kind,
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
        log_path=str(proc_log_path(proc_id)),
    )
    try:
        append_proc(proc)
    except Exception as exc:
        raise ProcSubmitError(f"could not record proc: {_one_line(exc)}") from exc

    supervisor_env = os.environ.copy()
    if env is not None:
        supervisor_env[_CHILD_ENV_VAR] = json.dumps(dict(env))
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.procs.supervisor",
                "--proc-id",
                proc_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=supervisor_env,
        )
    except (OSError, ValueError) as exc:
        message = f"could not start proc supervisor: {_one_line(exc)}"
        update_proc(
            proc_id,
            status="error",
            message=message,
            finished_at=_utc_timestamp(),
        )
        raise ProcSubmitError(message) from exc

    outcome = update_proc(proc_id, pid=process.pid)
    return outcome.proc or proc


def wait_for_proc(
    proc_id: str,
    *,
    timeout: float | None = None,
    on_line: LineCallback | None = None,
) -> Proc:
    """Wait for a proc, streaming newly retained log lines through ``on_line``."""
    started = time.monotonic()
    delay = _INITIAL_POLL_SECONDS
    seen_log = ""
    buffered = ""
    while True:
        proc = get_proc(proc_id)
        if proc is None:
            raise ProcControlError(f"no proc with id {proc_id!r}")

        current_log = _read_retained_log(Path(proc.log_path))
        new_text = _new_log_text(seen_log, current_log)
        seen_log = current_log
        if on_line is not None:
            buffered = _emit_complete_lines(buffered + new_text, on_line)

        if proc.status in TERMINAL_PROC_STATUSES:
            if on_line is not None and buffered:
                on_line(buffered.rstrip("\r"))
            return proc
        if timeout is not None and time.monotonic() - started >= timeout:
            raise TimeoutError(f"timed out waiting for proc {proc_id}")
        time.sleep(delay)
        delay = min(delay * 1.5, _MAX_POLL_SECONDS)


def kill_proc(proc_id: str) -> Proc:
    """Terminate a proc's process group and durably mark it killed."""
    proc = get_proc(proc_id)
    if proc is None:
        raise ProcControlError(f"no proc with id {proc_id!r}")
    if proc.status in TERMINAL_PROC_STATUSES:
        return proc
    if proc.kind == TUI_PROC_KIND:
        raise ProcControlError(
            "TUI-owned procs can only be killed from their owning ACE session"
        )
    if proc.pid is not None and not _supervisor_process_matches(proc):
        update_proc(
            proc_id,
            status="error",
            message="supervisor exited without reporting",
            finished_at=_utc_timestamp(),
        )
        raise ProcControlError(
            f"proc {proc_id} no longer belongs to its recorded supervisor"
        )

    errors: list[OSError] = []
    if proc.pid is not None:
        _signal_target(os.kill, proc.pid, errors)
    if errors:
        error = errors[0]
        if isinstance(error, PermissionError):
            raise ProcControlError(
                f"permission denied killing proc {proc_id}"
            ) from error
        raise ProcControlError(f"could not kill proc {proc_id}: {error}") from error

    outcome = update_proc(
        proc_id,
        status="killed",
        message="proc killed",
        finished_at=_utc_timestamp(),
    )
    if outcome.proc is None:
        raise ProcControlError(f"proc {proc_id!r} disappeared before it was killed")
    return outcome.proc


def reconcile_running_procs() -> list[Proc]:
    """Mark active rows whose supervisor died without terminalizing them."""
    reconciled: list[Proc] = []
    for proc in read_procs(status=ACTIVE_PROC_STATUSES):
        if not _is_orphaned(proc):
            continue
        current = get_proc(proc.proc_id)
        if current is None or current.status not in ACTIVE_PROC_STATUSES:
            continue
        outcome = update_proc(
            proc.proc_id,
            status="error",
            message="supervisor exited without reporting",
            finished_at=_utc_timestamp(),
        )
        if outcome.proc is not None:
            reconciled.append(outcome.proc)
    return reconciled


def _is_orphaned(proc: Proc) -> bool:
    """Return whether an active row's owner is gone without a terminal write."""
    if proc.pid is not None:
        if proc.kind in _SUPERVISOR_OWNED_KINDS:
            return not _supervisor_process_matches(proc)
        return not is_process_running(proc.pid)
    # No supervisor pid yet. A submit stamps one within milliseconds of
    # appending the row, and mirrored in-TUI procs are owned by their own
    # process, so only a stale supervisor-owned row is a genuine ghost:
    # reconciling a just-submitted row would race its supervisor to a terminal
    # status the store then refuses to move off.
    if proc.kind not in _SUPERVISOR_OWNED_KINDS:
        return False
    return _age_seconds(proc.created_at) >= _UNCLAIMED_GRACE_SECONDS


def _supervisor_process_matches(proc: Proc) -> bool:
    """Reject dead or PID-reused supervisors before trusting their PID."""
    pid = proc.pid
    if pid is None or not is_process_running(pid):
        return False
    try:
        argv = [
            value.decode("utf-8", errors="replace")
            for value in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if value
        ]
    except OSError:
        # Non-Linux and restricted /proc environments retain the existing
        # liveness-only behavior.
        return True
    try:
        module_index = argv.index("-m")
        proc_id_index = argv.index("--proc-id")
    except ValueError:
        return False
    return (
        module_index + 1 < len(argv)
        and argv[module_index + 1] == "sase.procs.supervisor"
        and proc_id_index + 1 < len(argv)
        and argv[proc_id_index + 1] == proc.proc_id
    )


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
        raise ProcSubmitError("proc command must contain a non-empty argv")
    return command


def _validated_cwd(cwd: str | Path) -> Path:
    path = Path(cwd).expanduser()
    if not path.is_dir():
        raise ProcSubmitError(f"proc cwd is not an existing directory: {path}")
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
    "ProcControlError",
    "ProcSubmitError",
    "kill_proc",
    "reconcile_running_procs",
    "submit_detached_proc",
    "submit_proc",
    "wait_for_proc",
]
