"""Foreground ToolRun executor: begin-before-spawn, two pumps, fail-open."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, TextIO

from sase.config.tools import load_project_tool_catalog
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_finish
from sase.supervision.logs import pump_output
from sase.tool.argv import ResolvedToolArgv, ToolRunUsageError, resolve_run_argv
from sase.tool.liveness import current_boot_id, reconcile_unsettled_tool_runs
from sase.tool.logs import (
    BoundedLogSink,
    LogSinkError,
    RunLogBudget,
    log_policy,
    prepare_run_paths,
)
from sase.tool.ownership import (
    ToolRunOwnerConflict,
    ToolRunOwnership,
    compact_requested,
    resolve_ownership,
)
from sase.tool.stage_protocol import (
    StageIngestor,
    format_unattributed_line,
    unattributed_from_stages,
)

# tools/_run_silent_record.py appends JSONL; this executor only tails and ingests.


_TOOL_RUN_ID_ENV = "SASE_TOOL_RUN_ID"
_TOOL_RUN_EVENTS_ENV = "SASE_TOOL_RUN_EVENTS"
_TERM_ESCALATE_SECONDS = 5.0
_KILL_WAIT_SECONDS = 2.0
_WARN_NOT_RECORDED = "sase: run not recorded"
_WARN_INCOMPLETE = "sase: recording incomplete"


@dataclass(frozen=True)
class ToolRunCliRequest:
    """Parsed ``sase tool run`` controls."""

    quiet: bool
    verbose: bool
    tail_lines: int
    words: tuple[str, ...]


class _SignalState:
    def __init__(self) -> None:
        self.sigint = False
        self.sigterm = False
        self.pgid: int | None = None
        self._forwarded: set[int] = set()
        self._lock = threading.Lock()

    def handler(self, signum: int, _frame: object) -> None:
        with self._lock:
            if signum == signal.SIGINT:
                self.sigint = True
            elif signum == signal.SIGTERM:
                self.sigterm = True
            self._forward_locked(signum)

    def bind_pgid(self, pgid: int) -> None:
        with self._lock:
            self.pgid = pgid
            if self.sigint:
                self._forward_locked(signal.SIGINT)
            if self.sigterm:
                self._forward_locked(signal.SIGTERM)

    def _forward_locked(self, signum: int) -> None:
        if self.pgid is None or signum in self._forwarded:
            return
        self._forwarded.add(signum)
        try:
            os.killpg(self.pgid, signum)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def execute_tool_run(request: ToolRunCliRequest) -> int:
    """Run one named or ad-hoc command and return the child-or-signal exit."""

    if request.quiet and request.verbose:
        print(
            "-q/--quiet and -v/--verbose cannot be used together",
            file=sys.stderr,
        )
        return 2
    if request.tail_lines < 0:
        print("-T/--tail-lines must be >= 0", file=sys.stderr)
        return 2
    try:
        resolved = resolve_run_argv(request.words)
        ownership = resolve_ownership(quiet=request.quiet)
    except (ToolRunUsageError, ToolRunOwnerConflict) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    compact = compact_requested(
        quiet=request.quiet,
        verbose=request.verbose,
        owns_output=ownership.owns_output,
    )
    reconcile_unsettled_tool_runs()

    signals = _SignalState()
    previous_int = signal.signal(signal.SIGINT, signals.handler)
    previous_term = signal.signal(signal.SIGTERM, signals.handler)
    try:
        if signals.sigint:
            return 130
        if signals.sigterm:
            return 143
        return _execute_resolved(
            request,
            resolved=resolved,
            ownership=ownership,
            compact=compact,
            signals=signals,
        )
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def _execute_resolved(
    request: ToolRunCliRequest,
    *,
    resolved: ResolvedToolArgv,
    ownership: ToolRunOwnership,
    compact: bool,
    signals: _SignalState,
) -> int:
    run_id = secrets.token_hex(16)
    events_path: Path | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    sink_warning = False
    try:
        events_path, stdout_path, stderr_path = prepare_run_paths(
            run_id, owns_output=ownership.owns_output
        )
    except (OSError, LogSinkError) as exc:
        sink_warning = True
        _warn_once(f"sase: retained-output sink unavailable ({exc}); using passthrough")
        compact = False

    if compact and (stdout_path is None or stderr_path is None):
        if not sink_warning:
            _warn_once("sase: retained-output sink unavailable; using passthrough")
        compact = False

    recorded = _begin_run(
        run_id,
        resolved=resolved,
        ownership=ownership,
        events_path=events_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    durable_id = run_id if recorded else None
    if not recorded:
        _warn_once(_WARN_NOT_RECORDED)
        durable_id = None
        events_path = None
        stdout_path = None
        stderr_path = None
        compact = False

    if signals.sigint or signals.sigterm:
        if recorded:
            _finish_run(
                run_id,
                state="interrupted" if signals.sigint else "signaled",
                exit_code=130 if signals.sigint else 143,
                signal_num=signal.SIGINT if signals.sigint else signal.SIGTERM,
                interruption_reason=(
                    "wrapper SIGINT" if signals.sigint else "wrapper SIGTERM"
                ),
                duration_ms=0,
            )
        return 130 if signals.sigint else 143

    child_env = _child_env(
        recorded=recorded, run_id=durable_id, events_path=events_path
    )
    started = time.monotonic()
    try:
        proc = _spawn(resolved.argv, cwd=resolved.cwd, env=child_env)
    except OSError as exc:
        exit_code = _spawn_exit_code(exc)
        diagnostic = _spawn_diagnostic(exc, resolved.argv)
        print(diagnostic, file=sys.stderr)
        if recorded:
            _finish_run(
                run_id,
                state="failed",
                exit_code=exit_code,
                diagnostics=[diagnostic],
                duration_ms=_duration_ms(started),
            )
        return exit_code

    child_pid = proc.pid
    try:
        child_pgid = os.getpgid(proc.pid)
    except OSError:
        child_pgid = proc.pid
    signals.bind_pgid(child_pgid)

    policy = log_policy()
    budget = RunLogBudget(int(policy.get("run_log_max_bytes") or 0))
    stdout_sink = (
        BoundedLogSink(stdout_path, budget, tail_lines=request.tail_lines)
        if stdout_path is not None
        else None
    )
    stderr_sink = (
        BoundedLogSink(stderr_path, budget, tail_lines=request.tail_lines)
        if stderr_path is not None
        else None
    )
    log_failed = False
    ingestor: StageIngestor | None = None
    if recorded and events_path is not None:
        ingestor = StageIngestor(
            path=events_path,
            run_id=run_id,
            compact=compact,
            event_max_bytes=int(policy.get("event_max_bytes") or 0),
        )

    def on_stdout(chunk: bytes) -> None:
        nonlocal log_failed
        if stdout_sink is not None:
            stdout_sink.write(chunk)
            if stdout_sink.failed:
                log_failed = True
        if not compact:
            _write_display(sys.stdout, chunk)

    def on_stderr(chunk: bytes) -> None:
        nonlocal log_failed
        if stderr_sink is not None:
            stderr_sink.write(chunk)
            if stderr_sink.failed:
                log_failed = True
        if not compact:
            _write_display(sys.stderr, chunk)

    if durable_id:
        _write_display(sys.stderr, f"sase tool run {durable_id}\n".encode())

    def on_tick() -> None:
        if ingestor is None:
            return
        for line in ingestor.tick():
            _write_display(sys.stderr, f"{line}\n".encode())

    pumps = _start_pumps(proc, on_stdout, on_stderr)
    wait_code = _wait_child(proc, signals, on_tick=on_tick)
    for pump in pumps:
        pump.join(timeout=5.0)
    if stdout_sink is not None:
        stdout_sink.close()
    if stderr_sink is not None:
        stderr_sink.close()
    duration_ms = _duration_ms(started)
    ingest_diagnostics: list[str] = []
    if ingestor is not None:
        for line in ingestor.flush():
            _write_display(sys.stderr, f"{line}\n".encode())
        ingest_diagnostics = list(ingestor.diagnostics)
    if log_failed and recorded:
        _warn_once(_WARN_INCOMPLETE)

    state, exit_code, signal_num, interruption = _settlement(wait_code, signals)
    if recorded:
        finished = _finish_run(
            run_id,
            state=state,
            exit_code=exit_code,
            signal_num=signal_num,
            interruption_reason=interruption,
            duration_ms=duration_ms,
            child_pid=child_pid,
            child_pgid=child_pgid,
            diagnostics=ingest_diagnostics or None,
        )
        if not finished:
            _warn_once(_WARN_INCOMPLETE)
        _write_footer(
            durable_id=durable_id,
            state=state,
            exit_code=exit_code,
            duration_ms=duration_ms,
            compact=compact,
            tail_lines=request.tail_lines,
            stdout_sink=stdout_sink,
            stderr_sink=stderr_sink,
            stages=list(ingestor.stages.values()) if ingestor is not None else (),
        )
    return exit_code


def _begin_run(
    run_id: str,
    *,
    resolved: ResolvedToolArgv,
    ownership: ToolRunOwnership,
    events_path: Path | None,
    stdout_path: Path | None,
    stderr_path: Path | None,
) -> bool:
    wrapper_pid = os.getpid()
    identity = process_identity_token(wrapper_pid)
    boot_id, _, _ = identity.partition(":") if identity else ("", "", "")
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "definition": resolved.definition,
        "extra_args": list(resolved.extra_args),
        "display_argv": list(resolved.display_argv),
        "project": _project_identity(),
        "agent": (os.environ.get("SASE_AGENT_NAME") or "").strip() or None,
        "workspace": (os.environ.get("SASE_WORKSPACE_NUM") or "").strip() or None,
        "bead": (
            (
                os.environ.get("SASE_BEAD_ID") or os.environ.get("SASE_BEAD") or ""
            ).strip()
            or None
        ),
        "owner_kind": ownership.owner_kind,
        "owner_id": ownership.owner_id,
        "parent_run_id": ownership.parent_run_id,
        "wrapper_pid": wrapper_pid,
        "boot_id": boot_id or current_boot_id() or None,
        "process_start_identity": identity or None,
        "events_path": str(events_path) if events_path is not None else None,
        "log_stdout_path": str(stdout_path) if stdout_path is not None else None,
        "log_stderr_path": str(stderr_path) if stderr_path is not None else None,
        "commit_running": True,
    }
    if resolved.tool_name:
        request["tool_name"] = resolved.tool_name
    if resolved.private_argv is not None:
        request["private_argv"] = list(resolved.private_argv)
    try:
        started = tool_run_begin(request)
    except Exception:  # noqa: BLE001 - recording failure is fail-open.
        return False
    run = started.get("run") if isinstance(started, dict) else None
    return isinstance(run, dict) and str(run.get("state") or "") == "running"


def _finish_run(
    run_id: str,
    *,
    state: str,
    exit_code: int | None,
    duration_ms: int | None,
    signal_num: int | None = None,
    interruption_reason: str | None = None,
    child_pid: int | None = None,
    child_pgid: int | None = None,
    diagnostics: list[str] | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "state": state,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    if signal_num is not None:
        payload["signal"] = signal_num
    if interruption_reason:
        payload["interruption_reason"] = interruption_reason
    if child_pid is not None:
        payload["child_pid"] = child_pid
    if child_pgid is not None:
        payload["child_pgid"] = child_pgid
    if diagnostics:
        payload["diagnostics"] = diagnostics
    try:
        tool_run_finish(payload)
    except Exception:  # noqa: BLE001 - never change the child result.
        return False
    return True


def _spawn(
    argv: tuple[str, ...],
    *,
    cwd: str | None,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _child_env(
    *,
    recorded: bool,
    run_id: str | None,
    events_path: Path | None,
) -> dict[str, str]:
    env = os.environ.copy()
    if recorded and run_id:
        env[_TOOL_RUN_ID_ENV] = run_id
        if events_path is not None:
            env[_TOOL_RUN_EVENTS_ENV] = str(events_path)
        return env
    env.pop(_TOOL_RUN_ID_ENV, None)
    env.pop(_TOOL_RUN_EVENTS_ENV, None)
    return env


def _start_pumps(
    proc: subprocess.Popen[bytes],
    on_stdout: Callable[[bytes], None],
    on_stderr: Callable[[bytes], None],
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    if proc.stdout is not None:
        thread = threading.Thread(
            target=_pump_child_stream,
            args=(proc.stdout, on_stdout),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    if proc.stderr is not None:
        thread = threading.Thread(
            target=_pump_child_stream,
            args=(proc.stderr, on_stderr),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return threads


def _pump_child_stream(stream: BinaryIO, callback: Callable[[bytes], None]) -> None:
    # Signals must stay on the wrapper's main thread. A SIGTERM/SIGINT delivered
    # to a pump thread would take the default terminate action and skip finish().
    blocker = getattr(signal, "pthread_sigmask", None)
    if blocker is not None:
        blocker(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    pump_output(stream, callback)


def _wait_child(
    proc: subprocess.Popen[bytes],
    signals: _SignalState,
    *,
    on_tick: Callable[[], None] | None = None,
) -> int | None:
    escalate_at: float | None = None
    while True:
        try:
            return proc.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            if on_tick is not None:
                try:
                    on_tick()
                except Exception:  # noqa: BLE001 - ingest cannot change the child.
                    pass
            if (signals.sigint or signals.sigterm) and escalate_at is None:
                escalate_at = time.monotonic() + _TERM_ESCALATE_SECONDS
            if escalate_at is not None and time.monotonic() >= escalate_at:
                if signals.pgid is not None:
                    try:
                        os.killpg(signals.pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                try:
                    return proc.wait(timeout=_KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    return proc.poll()


def _settlement(
    wait_code: int | None, signals: _SignalState
) -> tuple[str, int, int | None, str | None]:
    if signals.sigint:
        return "interrupted", 130, signal.SIGINT, "wrapper SIGINT"
    if signals.sigterm:
        return "signaled", 143, signal.SIGTERM, "wrapper SIGTERM"
    if wait_code is None:
        return "failed", 1, None, None
    if wait_code < 0:
        sig = -wait_code
        return "signaled", 128 + sig, sig, None
    if wait_code == 0:
        return "succeeded", 0, None, None
    return "failed", wait_code, None, None


def _write_footer(
    *,
    durable_id: str | None,
    state: str,
    exit_code: int,
    duration_ms: int,
    compact: bool,
    tail_lines: int,
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
    stages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> None:
    dropped = 0
    if stdout_sink is not None:
        dropped += stdout_sink.dropped
    if stderr_sink is not None:
        dropped += stderr_sink.dropped
    attribution = (
        unattributed_from_stages(list(stages), duration_ms) if stages else None
    )
    if compact:
        line = f"{state}"
        if exit_code:
            line += f"/{exit_code}"
        line += f"  {duration_ms}ms\n"
        _write_display(sys.stderr, line.encode())
        if attribution is not None:
            _write_display(
                sys.stderr, f"{format_unattributed_line(attribution)}\n".encode()
            )
        if state != "succeeded" and tail_lines > 0:
            tail = _compact_tail(stdout_sink, stderr_sink, tail_lines)
            if tail:
                _write_display(sys.stderr, tail.encode("utf-8", "replace"))
                if not tail.endswith("\n"):
                    _write_display(sys.stderr, b"\n")
        if durable_id:
            _write_display(
                sys.stderr,
                f"sase tool show {durable_id} -l\n".encode(),
            )
        return
    extra = f"  dropped={dropped}B" if dropped else ""
    _write_display(
        sys.stderr,
        f"{state}  exit={exit_code}  duration={duration_ms}ms{extra}\n".encode(),
    )
    if attribution is not None:
        _write_display(
            sys.stderr, f"{format_unattributed_line(attribution)}\n".encode()
        )


def _compact_tail(
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
    tail_lines: int,
) -> str:
    parts: list[str] = []
    if stdout_sink is not None:
        parts.append(stdout_sink.tail_text(tail_lines))
    if stderr_sink is not None:
        parts.append(stderr_sink.tail_text(tail_lines))
    combined = "".join(parts)
    if not combined:
        return ""
    lines = combined.splitlines(keepends=True)
    return "".join(lines[-tail_lines:])


def _write_display(stream: TextIO, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    try:
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            stream.write(data.decode("utf-8", "replace"))
            stream.flush()
    except OSError:
        pass


def _spawn_exit_code(exc: OSError) -> int:
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return 127
    return 126


def _spawn_diagnostic(exc: OSError, argv: tuple[str, ...]) -> str:
    program = argv[0] if argv else ""
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return f"executable not found: {program}"
    if exc.errno in {errno.EACCES, errno.EPERM, errno.EISDIR}:
        return f"not executable: {program}"
    return f"failed to launch {program}: {exc}"


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _project_identity() -> str:
    try:
        return load_project_tool_catalog().project
    except Exception:  # noqa: BLE001 - attribution still works without catalog.
        return (
            os.environ.get("SASE_PROJECT")
            or os.environ.get("SASE_PROJECT_NAME")
            or "unknown"
        ).strip() or "unknown"


def _warn_once(message: str) -> None:
    print(message, file=sys.stderr)


__all__ = ["ToolRunCliRequest", "execute_tool_run"]
