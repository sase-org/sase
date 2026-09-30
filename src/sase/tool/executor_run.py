"""Foreground ToolRun run body: spawn, pumps, settlement, and footer."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_observe
from sase.telemetry.metrics import (
    TOOL_RUN_RECORDING_ERRORS,
    TOOL_RUN_SETTLEMENTS,
)
from sase.tool._executor_shared import default_continuation_mode
from sase.tool.demand import (
    build_resource_usage,
    demand_file_path,
    read_demand_grants,
    record_run_demand,
)
from sase.tool.executor_display import (
    duration_ms_since,
    warn_once,
    write_display,
    write_run_footer,
)
from sase.tool.executor_models import RecordedRunContext
from sase.tool.executor_process import (
    ChildExit,
    child_env,
    settle_wait_code,
    should_merge_streams,
    spawn_child,
    spawn_diagnostic,
    spawn_exit_code,
    start_output_pumps,
    wait_child,
)
from sase.tool.executor_recording import finish_tool_run
from sase.tool.executor_signals import SignalState
from sase.tool.executor_triage import settle_failure_triage
from sase.tool.logs import (
    BoundedLogSink,
    RunLogBudget,
    log_policy,
    log_write_diagnostics,
    record_truncation,
    truncation_diagnostics,
)
from sase.tool.observe import inc_tool_metric, observe_fingerprint
from sase.tool.receipts import settle_receipt_for_run
from sase.tool.sample import LoadSampler
from sase.tool.stage_protocol import StageIngestor

_WARN_INCOMPLETE = "sase: recording incomplete"


def run_recorded_body(ctx: RecordedRunContext, signals: SignalState) -> int:
    """Run the shared post-begin body for foreground and adopted runs."""

    run_id = ctx.run_id
    recorded = ctx.recorded
    resolved = ctx.resolved
    durable_id = run_id if recorded else None

    fingerprint_before: dict[str, Any] | None = None
    if recorded:
        fingerprint_before = observe_fingerprint(resolved)

    if (
        signals.sigint
        or signals.sigterm
        or _stop_requested(ctx)
        or _timeout_requested(ctx)
    ):
        stop = _stop_requested(ctx)
        timeout = not stop and _timeout_requested(ctx)
        if recorded:
            if stop:
                state = "signaled"
                exit_code = None
                sig = None
                reason = "wrapper SIGTERM"
                cause = "stop_requested"
            elif timeout:
                # The owner's supervisor signaled for a timeout before the
                # command started; core allows an exit code and signal here.
                state = "signaled"
                exit_code = 143
                sig = signal.SIGTERM
                reason = "wrapper SIGTERM"
                cause = "timeout"
            elif signals.sigint:
                state = "interrupted"
                exit_code = 130
                sig = signal.SIGINT
                reason = "wrapper SIGINT"
                cause = "interrupt"
            else:
                state = "signaled"
                exit_code = 143
                sig = signal.SIGTERM
                reason = "wrapper SIGTERM"
                cause = "signal"
            finish_tool_run(
                run_id,
                state=state,
                exit_code=exit_code,
                signal_num=sig,
                interruption_reason=reason,
                duration_ms=0,
                fingerprint_before=fingerprint_before,
                fingerprint_after=observe_fingerprint(resolved) if recorded else None,
                terminal_cause=cause,
            )
            settle_receipt_for_run(run_id, resolved)
            inc_tool_metric(
                TOOL_RUN_SETTLEMENTS,
                state=state,
            )
        if signals.sigint and not (stop or timeout):
            return 130
        return 143 if (signals.sigterm or stop or timeout) else 130

    child_env_map = child_env(
        recorded=recorded,
        run_id=durable_id,
        events_path=ctx.events_path,
        resolved=resolved,
        continuation_mode=(
            ctx.continuation_mode
            if ctx.continuation_mode is not None
            else default_continuation_mode(resolved)
        ),
    )
    has_owner = ctx.has_owner
    merged = should_merge_streams(owns_output=ctx.owns_output, compact=ctx.compact)
    started = time.monotonic()
    try:
        proc = spawn_child(
            resolved.argv,
            cwd=resolved.cwd,
            env=child_env_map,
            start_new_session=not has_owner,
            merged_streams=merged,
        )
    except OSError as exc:
        exit_code = spawn_exit_code(exc)
        diagnostic = spawn_diagnostic(exc, resolved.argv)
        if durable_id:
            write_display(sys.stderr, f"sase tool run {durable_id}\n".encode())
        print(diagnostic, file=sys.stderr)
        if recorded:
            # Core rejects an exit code alongside launch_failed, and the
            # existing ledger contract records 127/126 for spawn failures,
            # so a spawn failure settles failed/exited (the CLI still
            # returns 127/126). Launch_failed stays for hand-off runs whose
            # command was never started (no exit code).
            finish_tool_run(
                run_id,
                state="failed",
                exit_code=exit_code,
                diagnostics=[diagnostic],
                duration_ms=duration_ms_since(started),
                fingerprint_before=fingerprint_before,
                fingerprint_after=observe_fingerprint(resolved),
                terminal_cause="exited",
            )
            settle_receipt_for_run(run_id, resolved)
            inc_tool_metric(TOOL_RUN_SETTLEMENTS, state="failed")
        return exit_code

    child_pid = proc.pid
    try:
        child_pgid = os.getpgid(proc.pid)
    except OSError:
        child_pgid = proc.pid
    signals.bind_pgid(child_pgid)
    if recorded:
        _observe_spawned_child(
            run_id,
            child_pid=child_pid,
            child_pgid=child_pgid,
            fingerprint_before=fingerprint_before,
        )
        if ctx.demand_context is not None:
            record_run_demand(run_id, context=dict(ctx.demand_context))

    policy = log_policy()
    budget = RunLogBudget(int(policy.get("run_log_max_bytes") or 0))
    stdout_sink = (
        BoundedLogSink(ctx.stdout_path, budget, tail_lines=ctx.tail_lines)
        if ctx.stdout_path is not None
        else None
    )
    stderr_sink = (
        BoundedLogSink(ctx.stderr_path, budget, tail_lines=ctx.tail_lines)
        if ctx.stderr_path is not None
        else None
    )
    log_failed = False
    ingestor: StageIngestor | None = None
    sampler: LoadSampler | None = None
    if recorded and ctx.events_path is not None:
        ingestor = StageIngestor(
            path=ctx.events_path,
            run_id=run_id,
            compact=ctx.compact,
            event_max_bytes=int(policy.get("event_max_bytes") or 0),
        )
    if recorded:
        sampler = LoadSampler(run_id=run_id, started=started, child_pid=child_pid)
        sampler.maybe_sample(force=True)
        if sampler.write_failures:
            inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="sample")

    def on_stdout(chunk: bytes) -> None:
        nonlocal log_failed
        if stdout_sink is not None:
            stdout_sink.write(chunk)
            if stdout_sink.failed:
                log_failed = True
        if not ctx.compact:
            write_display(sys.stdout, chunk)

    def on_stderr(chunk: bytes) -> None:
        nonlocal log_failed
        if stderr_sink is not None:
            stderr_sink.write(chunk)
            if stderr_sink.failed:
                log_failed = True
        if not ctx.compact:
            write_display(sys.stderr, chunk)

    def on_merged(chunk: bytes) -> None:
        # One pipe carries both child streams in write order. Retain the
        # interleaved bytes in the stdout log (the stderr log stays empty)
        # and pass them through once, to stdout: both wrapper fds name the
        # same target whenever this mode is selected.
        nonlocal log_failed
        if stdout_sink is not None:
            stdout_sink.write(chunk)
            if stdout_sink.failed:
                log_failed = True
        if not ctx.compact:
            write_display(sys.stdout, chunk)

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

    # With a merged pipe proc.stderr is None, so the second callback is never
    # invoked and a single pump drains the child's write order.
    pumps = start_output_pumps(proc, on_merged if merged else on_stdout, on_stderr)
    wait_exit = wait_child(proc, signals, on_tick=on_tick, escalate=not has_owner)
    if sampler is not None:
        sampler.stop_tree_sampling()
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
    log_write_facts = log_write_diagnostics(stdout_sink, stderr_sink)
    if recorded:
        record_truncation(ctx.events_path, run_id, truncation)
    if log_failed and recorded:
        warn_once(_WARN_INCOMPLETE)

    state, exit_code, signal_num, interruption = settle_wait_code(
        wait_exit.code, signals
    )
    if exit_code == 0 and ingestor is not None and ingestor.has_unfinished_continuation:
        # Core rejects a ``failed`` run carrying the child's successful status.
        # The wrapper therefore records the safety-net failure as exit 1, the
        # sole intentional departure from the child's process result.
        state = "failed"
        exit_code = 1
        signal_num = None
        interruption = None
        ingest_diagnostics.append("continuation_unfinished")
    if state == "interrupted":
        cause = "interrupt"
    elif state == "signaled":
        # A forwarded SIGTERM that settles a run with a durable stop
        # request is a requested stop, not an anonymous signal. The core
        # rejects stop_requested finishes carrying an exit code or signal,
        # so a requested stop settles without either (like the pre-spawn
        # path); the CLI still returns the signal-mapped code below. A
        # signal the owner sent for a timeout is a timeout, which keeps the
        # exit code and signal.
        if _stop_requested(ctx):
            cause = "stop_requested"
        elif _timeout_requested(ctx):
            cause = "timeout"
        else:
            cause = "signal"
    else:
        cause = "exited"
    cli_code = exit_code
    recorded_exit: int | None = exit_code
    recorded_signal: int | None = signal_num
    if cause == "stop_requested":
        recorded_exit = None
        recorded_signal = None
    if recorded:
        _record_run_usage(run_id, wait_exit, sampler, ctx.events_path)
        fingerprint_after = observe_fingerprint(resolved)
        finished = finish_tool_run(
            run_id,
            state=state,
            exit_code=recorded_exit,
            signal_num=recorded_signal,
            interruption_reason=interruption,
            duration_ms=duration_ms,
            child_pid=child_pid,
            child_pgid=child_pgid,
            diagnostics=[*ingest_diagnostics, *truncation, *log_write_facts] or None,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
            terminal_cause=cause,
        )
        if not finished:
            warn_once(_WARN_INCOMPLETE)
            inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="finish")
        inc_tool_metric(TOOL_RUN_SETTLEMENTS, state=state)
        triage = settle_failure_triage(
            ctx=ctx,
            fingerprint_before=fingerprint_before,
            ingestor=ingestor,
            state=state,
        )
        # Receipt minting runs after the E3 verdict has settled so the same
        # frozen run feeds Rust eligibility; foreground and adopted workers
        # share this body, so both paths settle identically.
        settle_receipt_for_run(run_id, resolved)
        write_run_footer(
            durable_id=durable_id,
            state=state,
            # The footer reports the process outcome (the signal-mapped
            # code); the ledger row for a requested stop carries no code.
            exit_code=cli_code,
            duration_ms=duration_ms,
            compact=ctx.compact,
            tail_lines=ctx.tail_lines,
            stdout_sink=stdout_sink,
            stderr_sink=stderr_sink,
            stages=list(ingestor.stages.values()) if ingestor is not None else (),
            truncation=truncation,
            triage=triage,
            triage_enabled=True,
        )
    return cli_code


def _record_run_usage(
    run_id: str,
    wait_exit: ChildExit,
    sampler: LoadSampler | None,
    events_path: Path | None,
) -> None:
    """Record one usage-plus-grants demand fragment after the reap.

    Runs after the child is reaped and before ``finish_tool_run``. The
    demand file may hold no grants (a child that never leased, or a
    passthrough run with no events path); usage is still recorded. Never
    raises and never changes the child's result.
    """

    demand_path = demand_file_path(events_path)
    grants: list[dict[str, Any]] = []
    grant_diagnostics: list[str] = []
    if demand_path is not None:
        grants, grant_diagnostics = read_demand_grants(demand_path, run_id)
    if sampler is not None:
        usage = build_resource_usage(
            wait_exit.rusage,
            peak_tree_rss_kib=sampler.peak_tree_rss_kib,
            tree_rss_samples=sampler.tree_rss_samples,
            availability=(
                [sampler.tree_rss_unavailable]
                if sampler.tree_rss_unavailable is not None
                else []
            ),
        )
    else:
        usage = build_resource_usage(wait_exit.rusage)
    record_run_demand(run_id, usage=usage, grants=grants, diagnostics=grant_diagnostics)


def _observe_spawned_child(
    run_id: str,
    *,
    child_pid: int,
    child_pgid: int,
    fingerprint_before: dict[str, Any] | None = None,
) -> None:
    """Persist the child's pid, pgid, and start identity right after spawn.

    Child facts used to reach the ledger only through ``finish_tool_run``, so
    a run killed seconds later settled ``lost`` with no reapable group.
    The pre-spawn fingerprint rides along so a mid-run stage triage can
    read ``base(R)`` and dirty paths before the run settles; finish
    resends the same value. Recording stays fail-open: an observe failure
    warns at most once and never changes the child's result.
    """

    try:
        identity = process_identity_token(child_pid)
    except Exception:  # noqa: BLE001 - identity is best-effort metadata.
        identity = ""
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "child_pid": child_pid,
        "child_pgid": child_pgid,
        "child_process_start_identity": identity or None,
    }
    if fingerprint_before is not None:
        request["fingerprint_before"] = fingerprint_before
    try:
        tool_run_observe(request)
    except Exception as exc:  # noqa: BLE001 - never change the child result.
        warn_once(f"sase: child facts not recorded ({exc})")
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="observe")


def _stop_requested(ctx: RecordedRunContext) -> bool:
    if ctx.stop_recorded is None:
        return False
    try:
        return bool(ctx.stop_recorded())
    except Exception:  # noqa: BLE001 - a stop probe must not break execution.
        return False


def _timeout_requested(ctx: RecordedRunContext) -> bool:
    if ctx.timeout_recorded is None:
        return False
    try:
        return bool(ctx.timeout_recorded())
    except Exception:  # noqa: BLE001 - a timeout probe must not break execution.
        return False


__all__ = ["run_recorded_body"]
