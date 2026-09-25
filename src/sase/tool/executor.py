"""Foreground ToolRun executor: begin-before-spawn, two pumps, fail-open."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import secrets
import signal
import sys
import threading
import time
from typing import Any

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import (
    tool_run_observe,
    tool_run_show,
    tool_run_triage_record,
    tool_run_triage_settle,
    tool_run_triage_show,
)
from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags
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
    should_merge_streams,
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
    log_write_diagnostics,
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
from sase.tool.triage_inputs import (
    gather_ancestry,
    gather_flake_baseline,
    gather_owner_candidates,
    gather_selection_records,
    triage_knobs,
)
from sase.tool.triage_display import footer_triage_lines

# tools/_run_silent_record.py appends JSONL; this executor only tails and ingests.

_WARN_NOT_RECORDED = "sase: run not recorded"
_WARN_INCOMPLETE = "sase: recording incomplete"
_TRIAGE_BUDGET_SECONDS = 5.0
_TRIAGE_GATHERER_SECONDS = 1.0
_TRIAGE_OUTPUT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ToolRunCliRequest:
    """Parsed ``sase tool run`` controls."""

    quiet: bool
    verbose: bool
    tail_lines: int
    words: tuple[str, ...]
    hand_off: bool = False
    tail_lines_explicit: bool = False
    keep_going: bool = False
    fail_fast: bool = False


@dataclass(frozen=True)
class RecordedRunContext:
    """Shared post-begin state for foreground and adopted runs."""

    run_id: str
    recorded: bool
    resolved: ResolvedToolArgv
    has_owner: bool
    owns_output: bool
    compact: bool
    tail_lines: int
    events_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    stop_recorded: Callable[[], bool] | None = None
    timeout_recorded: Callable[[], bool] | None = None
    continuation_mode: str | None = None


def execute_tool_run(request: ToolRunCliRequest) -> int:
    """Run one named or ad-hoc command and return the child-or-signal exit."""

    if request.keep_going and request.fail_fast:
        print(
            "-k/--keep-going and -x/--fail-fast cannot be used together",
            file=sys.stderr,
        )
        return 2
    if request.hand_off and (request.keep_going or request.fail_fast):
        print(
            "sase tool run -H cannot be used with -k/--keep-going or -x/--fail-fast",
            file=sys.stderr,
        )
        return 2
    if request.hand_off:
        from sase.tool.handoff_launch import execute_handoff

        return execute_handoff(request)
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
        continuation_mode = _continuation_mode(request, resolved)
    except (ToolRunUsageError, ToolRunOwnerConflict) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    compact = compact_requested(
        quiet=request.quiet,
        verbose=request.verbose,
        owns_output=ownership.owns_output,
    )
    # The executor owns the run lifecycle, so it also reaps identity-matched
    # survivors of lost runs. Read-only store paths (``tool runs``/``show``)
    # reconcile without reaping and never signal.
    reconcile_unsettled_tool_runs(reap_orphans=True)

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
            continuation_mode=continuation_mode,
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
    continuation_mode: str | None,
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
    if not recorded:
        warn_once(_WARN_NOT_RECORDED)
        events_path = None
        stdout_path = None
        stderr_path = None
        compact = False
        inc_tool_metric(TOOL_RUN_ATTEMPTS, result="unrecorded")
    else:
        inc_tool_metric(TOOL_RUN_ATTEMPTS, result="recorded")

    ctx = RecordedRunContext(
        run_id=run_id,
        recorded=recorded,
        resolved=resolved,
        has_owner=ownership.owner_kind is not None,
        owns_output=ownership.owns_output,
        compact=compact,
        tail_lines=request.tail_lines,
        events_path=events_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stop_recorded=_foreground_stop_probe(run_id) if recorded else None,
        continuation_mode=continuation_mode,
    )
    return run_recorded_body(ctx, signals)


def _foreground_stop_probe(run_id: str) -> Callable[[], bool]:
    """Return a probe reporting whether a durable stop request exists."""

    def _probe() -> bool:
        try:
            shown = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - unknown stop never blocks execution.
            return False
        run = shown.get("run") if isinstance(shown, dict) else None
        return isinstance(run, dict) and run.get("stop_request") is not None

    return _probe


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


def _default_continuation_mode(resolved: ResolvedToolArgv) -> str | None:
    """Return the normal continuation handshake for a resolved named tool."""

    is_run_silent = (
        not resolved.adhoc
        and resolved.tool_name is not None
        and str(resolved.definition.get("stages") or "none") == "run_silent"
    )
    return "never" if is_run_silent else None


def _recorded_agent_attribution() -> str:
    """Return the agent name this run would record, or an empty string.

    This mirrors the attribution ``build_begin_request`` persists: the
    foreground ``SASE_AGENT_NAME``, or ``SASE_TOOL_RUN_AGENT`` for an
    E1.5-wrapped run inside a monitor-owned proc.
    """

    return (os.environ.get("SASE_AGENT_NAME") or "").strip() or (
        os.environ.get("SASE_TOOL_RUN_AGENT") or ""
    ).strip()


def agent_default_continuation_mode(
    resolved: ResolvedToolArgv, agent: str | None
) -> str | None:
    """Return the handshake mode for a recorded run with *agent* attribution.

    With the failure-triage flag on, an agent-attributed run of a
    ``stages: run_silent`` named tool continues past all-KNOWN/FLAKY
    stages; every other run keeps fail-fast. Adopted monitor workers
    pass the run's stored agent so a starter-agent reservation inherits
    the same default through its recorded attribution.
    """

    default_mode = _default_continuation_mode(resolved)
    if default_mode is None:
        return None
    if agent and agent.strip() and _failure_triage_enabled():
        return "known"
    return default_mode


def _continuation_mode(
    request: ToolRunCliRequest, resolved: ResolvedToolArgv
) -> str | None:
    """Validate continuation controls and choose the child handshake mode."""

    default_mode = _default_continuation_mode(resolved)
    if request.keep_going or request.fail_fast:
        if default_mode is None:
            raise ToolRunUsageError(
                "-k/--keep-going and -x/--fail-fast require a named "
                "tool with stages: run_silent"
            )
        return "always" if request.keep_going else "never"
    if default_mode is None:
        return None
    return agent_default_continuation_mode(resolved, _recorded_agent_attribution())


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
            else _default_continuation_mode(resolved)
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
    wait_code = wait_child(proc, signals, on_tick=on_tick, escalate=not has_owner)
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

    state, exit_code, signal_num, interruption = settle_wait_code(wait_code, signals)
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
        triage = _settle_failure_triage(
            ctx=ctx,
            fingerprint_before=fingerprint_before,
            ingestor=ingestor,
            state=state,
        )
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
            triage_enabled=_failure_triage_enabled(),
        )
    return cli_code


def _failure_triage_enabled() -> bool:
    """Read the beta gate at use time; never resolve flags at import time."""

    try:
        return current_flags().enabled(FeatureFlag.tool_failure_triage)
    except Exception:  # noqa: BLE001 - a display gate must fail closed.
        return False


def _settle_failure_triage(
    *,
    ctx: RecordedRunContext,
    fingerprint_before: dict[str, Any] | None,
    ingestor: StageIngestor | None,
    state: str,
) -> dict[str, Any] | None:
    """Persist bounded failure triage without changing the child outcome.

    This sits after ``tool_run_finish`` so foreground and adopted workers use
    the same settled ledger row.  It deliberately returns diagnostics for the
    optional footer rather than raising into the process-result path.
    """

    if ctx.resolved.adhoc or not ctx.resolved.tool_name:
        return None
    deadline = time.monotonic() + _TRIAGE_BUDGET_SECONDS
    root = Path(ctx.resolved.cwd or os.getcwd())
    diagnostics: list[str] = []
    stages = _failed_stage_inputs(ingestor, ctx.events_path, diagnostics)
    run_output: str | None = None
    run_output_truncated = False
    if state != "succeeded" and not stages:
        run_output, run_output_truncated = _output_of_record(ctx, diagnostics)
    base = _fingerprint_base_head(fingerprint_before)
    project = ctx.resolved.resolved_project_identity()
    extra_args = ""
    if isinstance(fingerprint_before, dict):
        extra_args = str(fingerprint_before.get("extra_args_digest") or "")
    ancestry, ancestry_notes = (
        _gather_triage("ancestry", lambda: gather_ancestry(root, base), deadline)
        if base
        else ([], ["triage ancestry unavailable: base head missing"])
    )
    flake_baseline, baseline_notes = (
        _gather_triage(
            "flake baseline", lambda: gather_flake_baseline(root, base), deadline
        )
        if base
        else ([], ["triage flake baseline unavailable: base head missing"])
    )
    selection, selection_notes = _gather_triage(
        "selection records",
        lambda: gather_selection_records(
            project,
            project=project,
            tool=ctx.resolved.tool_name,
            extra_args_digest=extra_args,
        ),
        deadline,
    )
    owners, owner_notes = _gather_triage(
        "owner candidates", lambda: gather_owner_candidates(root), deadline
    )
    diagnostics.extend(
        str(note)
        for notes in (ancestry_notes, baseline_notes, selection_notes, owner_notes)
        for note in notes
    )
    if time.monotonic() >= deadline:
        return {
            "triaged": False,
            "diagnostics": [*diagnostics, "triage budget exceeded"],
        }
    request = {
        "run_id": ctx.run_id,
        "stages": stages,
        "run_output": run_output,
        "run_output_truncated": run_output_truncated,
        "project_root": str(root),
        "workspace_roots": [str(root)],
        "ancestry": ancestry,
        "flake_baseline": flake_baseline,
        "selection_records": selection,
        "owner_candidates": owners,
        "knobs": triage_knobs(),
        "continuation_mode": ctx.continuation_mode,
        "recipe_finished_ts": _recipe_finished_ts(ingestor),
        "now_ts": int(time.time()),
    }
    try:
        tool_run_triage_settle(
            request,
            busy_timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
        )
        # The settle response intentionally omits stage facts. Read back the
        # stored shape so the footer and explicit show surface share it.
        triage = tool_run_triage_show(
            {"run_id": ctx.run_id},
            busy_timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
        )
        triage, record_notes = _persist_continuation_decisions(
            ctx, ingestor, triage, deadline
        )
        triage["diagnostics"] = [
            *_string_items(triage.get("diagnostics")),
            *diagnostics,
            *record_notes,
        ]
        return triage
    except Exception as exc:  # noqa: BLE001 - triage must always fail open.
        return {"triaged": False, "diagnostics": [str(exc), *diagnostics]}


_DECISION_RECORD_MIN_SECONDS = 0.3
_EXTRACTION_STATUSES = frozenset(
    {"parsed", "generic", "output_missing", "output_truncated"}
)


def _continuation_decision_entries(
    ingestor: StageIngestor | None,
) -> list[dict[str, Any]]:
    """Project helper continuation records onto stored stage identities."""

    if ingestor is None:
        return []
    entries: list[dict[str, Any]] = []
    for record in ingestor.continuation_records:
        kind = str(record.get("kind") or "")
        if kind == "continued":
            decision = "continue"
        elif kind == "stopped":
            decision = "stop"
        else:
            continue
        stage_id = str(record.get("stage_id") or "")
        stage = ingestor.stages.get(stage_id) if stage_id else None
        stage_key = ""
        if isinstance(stage, dict):
            stage_key = str(stage.get("description") or "")
        if not stage_key:
            stage_key = str(record.get("description") or "")
        if not stage_id or not stage_key:
            continue
        elapsed = record.get("elapsed_ms")
        decided = record.get("decided_ts")
        entries.append(
            {
                "stage_id": stage_id,
                "stage_key": stage_key,
                "mode": str(record.get("mode") or ""),
                "decision": decision,
                "reason": str(record.get("reason") or ""),
                "elapsed_ms": elapsed if type(elapsed) is int else None,
                "decided_ts": decided if type(decided) is int else None,
            }
        )
    return entries


def _continuation_run_cost(
    records: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    """Return ``(first_continued_exit_code, extra_ms)`` for a run.

    The extra cost of continuing is the wall time from the first
    continued failure to the recipe finish marker, or to settlement
    when the finish marker is missing.
    """

    continued = [r for r in records if r.get("kind") == "continued"]
    if not continued:
        return None, None
    first_code: int | None = None
    first_ts: int | None = None
    first = continued[0]
    if type(first.get("exit_code")) is int:
        first_code = int(first["exit_code"])
    if type(first.get("decided_ts")) is int:
        first_ts = int(first["decided_ts"])
    finished = [r for r in records if r.get("kind") == "recipe_finished"]
    if finished:
        last = finished[-1]
        if type(last.get("first_continued_exit_code")) is int:
            first_code = int(last["first_continued_exit_code"])
        end = last.get("decided_ts")
        end_ts = int(end) if type(end) is int else int(time.time() * 1000)
    else:
        end_ts = int(time.time() * 1000)
    extra_ms = None if first_ts is None else max(0, end_ts - first_ts)
    return first_code, extra_ms


def _persist_continuation_decisions(
    ctx: RecordedRunContext,
    ingestor: StageIngestor | None,
    triage: dict[str, Any],
    deadline: float,
) -> tuple[dict[str, Any], list[str]]:
    """Persist helper continuation decisions and run cost facts.

    Settle stores items and labels but never sees the helper's
    ``continued``/``stopped`` records, so without this call a
    ``show -j`` stage would carry no decision and no continuation cost.
    Stored rows win on replay: an entry only fills a decision that is
    still NULL, and run facts only fill columns that are still NULL.
    """

    notes: list[str] = []
    if ingestor is None or not ctx.continuation_mode:
        return triage, notes
    entries = _continuation_decision_entries(ingestor)
    first_code, extra_ms = _continuation_run_cost(ingestor.continuation_records)
    if not entries and first_code is None and extra_ms is None:
        return triage, notes
    by_id: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for stage in _dict_items(triage.get("stages")):
        stage_id = stage.get("stage_id")
        if isinstance(stage_id, str) and stage_id:
            by_id.setdefault(stage_id, stage)
        stage_key = stage.get("stage_key")
        if isinstance(stage_key, str) and stage_key:
            by_key.setdefault(stage_key, stage)
    stages: list[dict[str, Any]] = []
    for entry in entries:
        if entry["decided_ts"] is None:
            notes.append(
                f"triage decision unmatched: {entry['stage_key']} (missing timestamp)"
            )
            continue
        stored = by_id.get(entry["stage_id"]) or by_key.get(entry["stage_key"])
        if stored is None:
            notes.append(f"triage decision unmatched: {entry['stage_key']}")
            continue
        if stored.get("extraction_status") not in _EXTRACTION_STATUSES:
            notes.append(
                f"triage decision unmatched: {entry['stage_key']} "
                "(unknown extraction status)"
            )
            continue
        stages.append(
            {
                "stage_key": stored.get("stage_key"),
                "stage_id": stored.get("stage_id") or entry["stage_id"],
                "extraction_status": stored.get("extraction_status"),
                "output_path": stored.get("output_path"),
                "decision": {
                    "mode": entry["mode"] or ctx.continuation_mode,
                    "decision": entry["decision"],
                    "reason": entry["reason"],
                    "elapsed_ms": entry["elapsed_ms"],
                    "decided_ts": entry["decided_ts"],
                },
                "items": [],
            }
        )
    if not stages and first_code is None and extra_ms is None:
        return triage, notes
    remaining = deadline - time.monotonic()
    if remaining <= _DECISION_RECORD_MIN_SECONDS:
        notes.append("triage decision record skipped: budget exhausted")
        return triage, notes
    try:
        tool_run_triage_record(
            {
                "run_id": ctx.run_id,
                "stages": stages,
                "run_facts": {
                    "continuation_mode": ctx.continuation_mode,
                    "recipe_finished_ts": _recipe_finished_ts(ingestor),
                    "first_continued_exit_code": first_code,
                    "continuation_extra_ms": extra_ms,
                    "repeat_of_run_id": None,
                    "triaged_ts": None,
                    "diagnostics": [],
                },
                "now_ts": int(time.time()),
            },
            busy_timeout_ms=max(1, int(remaining * 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - decisions must fail open.
        notes.append(f"triage decision record failed: {exc}")
        return triage, notes
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        notes.append("triage decision re-read skipped: budget exhausted")
        return triage, notes
    try:
        refreshed = tool_run_triage_show(
            {"run_id": ctx.run_id},
            busy_timeout_ms=max(1, int(remaining * 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - the first read still stands.
        notes.append(f"triage decision re-read failed: {exc}")
        return triage, notes
    if not isinstance(refreshed, dict):
        notes.append("triage decision re-read failed: malformed envelope")
        return triage, notes
    return refreshed, notes


def _gather_triage(
    name: str, callback: Callable[[], tuple[Any, list[str]]], deadline: float
) -> tuple[Any, list[str]]:
    """Await one optional gatherer only within its slice of the total budget."""

    remaining = min(_TRIAGE_GATHERER_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        return [], [f"triage {name} skipped: budget exhausted"]
    result: queue.Queue[object] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result.put(callback())
        except Exception as exc:  # noqa: BLE001 - gatherers are optional evidence.
            result.put(exc)

    thread = threading.Thread(target=run, daemon=True, name=f"sase-triage-{name}")
    thread.start()
    try:
        value = result.get(timeout=remaining)
    except queue.Empty:
        return [], [f"triage {name} timed out"]
    if isinstance(value, Exception):
        return [], [f"triage {name} failed: {value}"]
    if not isinstance(value, tuple) or len(value) != 2:
        return [], [f"triage {name} returned malformed evidence"]
    items, diagnostics = value
    return items, _string_items(diagnostics)


def _failed_stage_inputs(
    ingestor: StageIngestor | None,
    events_path: Path | None,
    diagnostics: list[str],
) -> list[dict[str, Any]]:
    if ingestor is None:
        return []
    inputs: list[dict[str, Any]] = []
    for stage_id, stage in ingestor.stages.items():
        if type(stage.get("exit_code")) is not int or int(stage["exit_code"]) == 0:
            continue
        metadata = ingestor.stage_outputs.get(stage_id) or {}
        output, missing = _read_stage_output(events_path, metadata.get("output_path"))
        if missing:
            diagnostics.append(
                f"triage stage output unavailable: {stage.get('description') or stage_id}"
            )
        inputs.append(
            {
                "stage_key": str(stage.get("description") or "*"),
                "stage_id": stage_id,
                "output": output,
                "truncated": bool(metadata.get("truncated")),
                "output_path": metadata.get("output_path"),
            }
        )
    return inputs


def _read_stage_output(
    events_path: Path | None, raw_path: object
) -> tuple[str | None, bool]:
    if events_path is None or not isinstance(raw_path, str) or not raw_path:
        return None, True
    try:
        root = events_path.parent.resolve()
        path = (root / raw_path).resolve()
        path.relative_to(root)
        data = path.read_bytes()
    except (OSError, ValueError):
        return None, True
    return data[-_TRIAGE_OUTPUT_BYTES:].decode("utf-8", "replace"), False


def _output_of_record(
    ctx: RecordedRunContext, diagnostics: list[str]
) -> tuple[str | None, bool]:
    chunks: list[bytes] = []
    for path in (ctx.stdout_path, ctx.stderr_path):
        if path is None:
            continue
        try:
            chunks.append(path.read_bytes())
        except OSError as exc:
            diagnostics.append(f"triage output of record unavailable: {exc}")
    if not chunks:
        return None, False
    joined = b"".join(chunks)
    return joined[-_TRIAGE_OUTPUT_BYTES:].decode("utf-8", "replace"), len(
        joined
    ) > _TRIAGE_OUTPUT_BYTES


def _fingerprint_base_head(fingerprint: dict[str, Any] | None) -> str:
    if not isinstance(fingerprint, dict):
        return ""
    for repo in _dict_items(fingerprint.get("repos")):
        head = repo.get("head")
        if isinstance(head, str) and head:
            return head
    return ""


def _recipe_finished_ts(ingestor: StageIngestor | None) -> int | None:
    if ingestor is None:
        return None
    for record in reversed(ingestor.continuation_records):
        if record.get("kind") == "recipe_finished":
            value = record.get("decided_ts")
            if type(value) is int:
                return value // 1000
    return None


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


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


__all__ = [
    "RecordedRunContext",
    "ToolRunCliRequest",
    "agent_default_continuation_mode",
    "execute_tool_run",
    "run_recorded_body",
]
