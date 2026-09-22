"""Foreground ToolRun executor: begin-before-spawn, two pumps, fail-open."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import signal
import sys
import time
from typing import Any

from sase.telemetry.metrics import (
    TOOL_RUN_ATTEMPTS,
    TOOL_RUN_RECORDING_ERRORS,
    TOOL_RUN_SETTLEMENTS,
)
from sase.tool.argv import ResolvedToolArgv, ToolRunUsageError, resolve_run_argv
from sase.tool.executor_display import (
    duration_ms_since,
    warn_once,
    write_display,
    write_run_footer,
)
from sase.tool.executor_process import (
    child_env,
    settle_wait_code,
    spawn_child,
    spawn_diagnostic,
    spawn_exit_code,
    start_output_pumps,
    wait_child,
)
from sase.tool.executor_recording import begin_tool_run, finish_tool_run
from sase.tool.executor_signals import SignalState
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.logs import (
    BoundedLogSink,
    LogSinkError,
    RunLogBudget,
    log_policy,
    prepare_run_paths,
    record_truncation,
    truncation_diagnostics,
)
from sase.tool.observe import inc_tool_metric, observe_fingerprint
from sase.tool.ownership import (
    ToolRunOwnerConflict,
    ToolRunOwnership,
    compact_requested,
    resolve_ownership,
)
from sase.tool.sample import LoadSampler
from sase.tool.stage_protocol import StageIngestor

# tools/_run_silent_record.py appends JSONL; this executor only tails and ingests.

_WARN_NOT_RECORDED = "sase: run not recorded"
_WARN_INCOMPLETE = "sase: recording incomplete"


@dataclass(frozen=True)
class ToolRunCliRequest:
    """Parsed ``sase tool run`` controls."""

    quiet: bool
    verbose: bool
    tail_lines: int
    words: tuple[str, ...]


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

    signals = SignalState()
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
    signals: SignalState,
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
        warn_once(f"sase: retained-output sink unavailable ({exc}); using passthrough")
        compact = False

    if compact and (stdout_path is None or stderr_path is None):
        if not sink_warning:
            warn_once("sase: retained-output sink unavailable; using passthrough")
        compact = False

    recorded = begin_tool_run(
        run_id,
        resolved=resolved,
        ownership=ownership,
        events_path=events_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    durable_id = run_id if recorded else None
    if not recorded:
        warn_once(_WARN_NOT_RECORDED)
        durable_id = None
        events_path = None
        stdout_path = None
        stderr_path = None
        compact = False
        inc_tool_metric(TOOL_RUN_ATTEMPTS, result="unrecorded")
    else:
        inc_tool_metric(TOOL_RUN_ATTEMPTS, result="recorded")

    fingerprint_before: dict[str, Any] | None = None
    if recorded:
        fingerprint_before = observe_fingerprint(resolved)

    if signals.sigint or signals.sigterm:
        if recorded:
            finish_tool_run(
                run_id,
                state="interrupted" if signals.sigint else "signaled",
                exit_code=130 if signals.sigint else 143,
                signal_num=signal.SIGINT if signals.sigint else signal.SIGTERM,
                interruption_reason=(
                    "wrapper SIGINT" if signals.sigint else "wrapper SIGTERM"
                ),
                duration_ms=0,
                fingerprint_before=fingerprint_before,
                fingerprint_after=observe_fingerprint(resolved) if recorded else None,
            )
            inc_tool_metric(
                TOOL_RUN_SETTLEMENTS,
                state="interrupted" if signals.sigint else "signaled",
            )
        return 130 if signals.sigint else 143

    child_env_map = child_env(
        recorded=recorded,
        run_id=durable_id,
        events_path=events_path,
        resolved=resolved,
    )
    started = time.monotonic()
    try:
        proc = spawn_child(resolved.argv, cwd=resolved.cwd, env=child_env_map)
    except OSError as exc:
        exit_code = spawn_exit_code(exc)
        diagnostic = spawn_diagnostic(exc, resolved.argv)
        if durable_id:
            write_display(sys.stderr, f"sase tool run {durable_id}\n".encode())
        print(diagnostic, file=sys.stderr)
        if recorded:
            finish_tool_run(
                run_id,
                state="failed",
                exit_code=exit_code,
                diagnostics=[diagnostic],
                duration_ms=duration_ms_since(started),
                fingerprint_before=fingerprint_before,
                fingerprint_after=observe_fingerprint(resolved),
            )
            inc_tool_metric(TOOL_RUN_SETTLEMENTS, state="failed")
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
    sampler: LoadSampler | None = None
    if recorded and events_path is not None:
        ingestor = StageIngestor(
            path=events_path,
            run_id=run_id,
            compact=compact,
            event_max_bytes=int(policy.get("event_max_bytes") or 0),
        )
    if recorded:
        sampler = LoadSampler(run_id=run_id, started=started)
        sampler.maybe_sample(force=True)
        if sampler.write_failures:
            inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="sample")

    def on_stdout(chunk: bytes) -> None:
        nonlocal log_failed
        if stdout_sink is not None:
            stdout_sink.write(chunk)
            if stdout_sink.failed:
                log_failed = True
        if not compact:
            write_display(sys.stdout, chunk)

    def on_stderr(chunk: bytes) -> None:
        nonlocal log_failed
        if stderr_sink is not None:
            stderr_sink.write(chunk)
            if stderr_sink.failed:
                log_failed = True
        if not compact:
            write_display(sys.stderr, chunk)

    if durable_id:
        write_display(sys.stderr, f"sase tool run {durable_id}\n".encode())

    def on_tick() -> None:
        if sampler is not None:
            before_failures = sampler.write_failures
            sampler.maybe_sample()
            if sampler.write_failures > before_failures:
                inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="sample")
        if ingestor is None:
            return
        for line in ingestor.tick():
            write_display(sys.stderr, f"{line}\n".encode())

    pumps = start_output_pumps(proc, on_stdout, on_stderr)
    wait_code = wait_child(proc, signals, on_tick=on_tick)
    for pump in pumps:
        pump.join(timeout=5.0)
    if stdout_sink is not None:
        stdout_sink.close()
    if stderr_sink is not None:
        stderr_sink.close()
    duration_ms = duration_ms_since(started)
    ingest_diagnostics: list[str] = []
    if sampler is not None:
        before_failures = sampler.write_failures
        sampler.maybe_sample(force=True)
        sampler.stop()
        if sampler.write_failures > before_failures:
            inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="sample")
    if ingestor is not None:
        for line in ingestor.flush():
            write_display(sys.stderr, f"{line}\n".encode())
        ingest_diagnostics = list(ingestor.diagnostics)
    truncation = truncation_diagnostics(stdout_sink, stderr_sink, budget)
    if recorded:
        record_truncation(events_path, run_id, truncation)
    if log_failed and recorded:
        warn_once(_WARN_INCOMPLETE)

    state, exit_code, signal_num, interruption = settle_wait_code(wait_code, signals)
    if recorded:
        fingerprint_after = observe_fingerprint(resolved)
        finished = finish_tool_run(
            run_id,
            state=state,
            exit_code=exit_code,
            signal_num=signal_num,
            interruption_reason=interruption,
            duration_ms=duration_ms,
            child_pid=child_pid,
            child_pgid=child_pgid,
            diagnostics=ingest_diagnostics or None,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
        )
        if not finished:
            warn_once(_WARN_INCOMPLETE)
            inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="finish")
        inc_tool_metric(TOOL_RUN_SETTLEMENTS, state=state)
        write_run_footer(
            durable_id=durable_id,
            state=state,
            exit_code=exit_code,
            duration_ms=duration_ms,
            compact=compact,
            tail_lines=request.tail_lines,
            stdout_sink=stdout_sink,
            stderr_sink=stderr_sink,
            stages=list(ingestor.stages.values()) if ingestor is not None else (),
            truncation=truncation,
        )
    return exit_code


__all__ = ["ToolRunCliRequest", "execute_tool_run"]
