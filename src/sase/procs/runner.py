"""Submission and control APIs for detached procs."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sase.ace.hooks.processes import is_process_running

from .models import (
    ACTIVE_PROC_STATUSES,
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    TERMINAL_PROC_STATUSES,
    TUI_PROC_KIND,
    Proc,
)
from .request import ProcSubmitRequest
from .service import (
    ProcControlError,
    ProcSubmitError,
    reconcile_proc_shells,
    stop_proc_shell,
    submit_proc_request,
)
from .settlement import is_proc_shell_row
from .store import get_proc, read_procs, update_proc

LineCallback = Callable[[str], None]

_INITIAL_POLL_SECONDS = 0.05
_MAX_POLL_SECONDS = 0.5

# How long a supervisor-owned legacy row may sit without a supervisor pid
# before reconciliation treats it as a submit that died before it spawned.
_UNCLAIMED_GRACE_SECONDS = 60.0

# Kinds whose legacy rows are driven by ``sase.procs.legacy_supervisor``.
_SUPERVISOR_OWNED_KINDS = frozenset({COMMAND_PROC_KIND, DETACHED_PROC_KIND})


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
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> Proc:
    """Record and detach a command proc under the proc supervisor."""
    return submit_proc_request(
        ProcSubmitRequest(
            argv=argv,
            kind=COMMAND_PROC_KIND,
            label=label,
            cwd=cwd,
            session_id=session_id,
            session_label=_session_label(session_id),
            project=project,
            workspace_num=workspace_num,
            tags=tags,
            origin=origin,
            cl_name=cl_name,
            env=env,
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
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
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> Proc:
    """Record and detach a proc that no interactive session owns.

    A detached row carries no ``session_id``, so every surface keeps it in
    scope no matter which session — if any — submitted it. ``origin`` is the
    only record of where the work came from and is therefore required.
    """
    return submit_proc_request(
        ProcSubmitRequest(
            argv=argv,
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
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    )


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
    """Stop a proc: intent plus signal for proc-shells, legacy terminal write."""
    proc = get_proc(proc_id)
    if proc is None:
        raise ProcControlError(f"no proc with id {proc_id!r}")
    if proc.status in TERMINAL_PROC_STATUSES:
        return proc
    if proc.kind == TUI_PROC_KIND:
        raise ProcControlError(
            "TUI-owned procs can only be killed from their owning ACE session"
        )
    if is_proc_shell_row(proc):
        return stop_proc_shell(proc)
    return _legacy_kill_proc(proc)


def reconcile_running_procs() -> list[Proc]:
    """Mark active rows whose supervisor died without terminalizing them."""
    reconciled = reconcile_proc_shells()
    for proc in read_procs(status=ACTIVE_PROC_STATUSES):
        if is_proc_shell_row(proc) or not _legacy_is_orphaned(proc):
            continue
        current = get_proc(proc.proc_id)
        if current is None or current.status not in ACTIVE_PROC_STATUSES:
            continue
        if is_proc_shell_row(current):
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


def _legacy_kill_proc(proc: Proc) -> Proc:
    if proc.pid is not None and not _supervisor_process_matches(proc):
        update_proc(
            proc.proc_id,
            status="error",
            message="supervisor exited without reporting",
            finished_at=_utc_timestamp(),
        )
        raise ProcControlError(
            f"proc {proc.proc_id} no longer belongs to its recorded supervisor"
        )

    errors: list[OSError] = []
    if proc.pid is not None:
        _signal_target(os.kill, proc.pid, errors)
    if errors:
        error = errors[0]
        if isinstance(error, PermissionError):
            raise ProcControlError(
                f"permission denied killing proc {proc.proc_id}"
            ) from error
        raise ProcControlError(
            f"could not kill proc {proc.proc_id}: {error}"
        ) from error

    outcome = update_proc(
        proc.proc_id,
        status="killed",
        message="proc killed",
        finished_at=_utc_timestamp(),
    )
    if outcome.proc is None:
        raise ProcControlError(
            f"proc {proc.proc_id!r} disappeared before it was killed"
        )
    return outcome.proc


def _legacy_is_orphaned(proc: Proc) -> bool:
    if proc.pid is not None:
        if proc.kind in _SUPERVISOR_OWNED_KINDS:
            return not _supervisor_process_matches(proc)
        return not is_process_running(proc.pid)
    if proc.kind not in _SUPERVISOR_OWNED_KINDS:
        return False
    return _age_seconds(proc.created_at) >= _UNCLAIMED_GRACE_SECONDS


def _supervisor_process_matches(proc: Proc) -> bool:
    """Compatibility alias used by CLI tests that stub supervisor liveness."""
    return _legacy_supervisor_process_matches(proc)


def _legacy_supervisor_process_matches(proc: Proc) -> bool:
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
        return True
    try:
        module_index = argv.index("-m")
        proc_id_index = argv.index("--proc-id")
    except ValueError:
        return False
    module = argv[module_index + 1] if module_index + 1 < len(argv) else ""
    return (
        module in {"sase.procs.supervisor", "sase.procs.legacy_supervisor"}
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
    "submit_proc_request",
    "wait_for_proc",
]
