"""Foreground ToolRun entrypoint: validation, reservation, and spawn setup."""

from __future__ import annotations

from collections.abc import Callable
import os
import secrets
import signal
import sys
from pathlib import Path

from sase.core.tool_run import tool_run_show
from sase.telemetry.metrics import TOOL_RUN_ATTEMPTS
from sase.tool._executor_shared import default_continuation_mode
from sase.tool.argv import ResolvedToolArgv, ToolRunUsageError, resolve_run_argv
from sase.tool.demand import demand_context as build_demand_context
from sase.tool.executor_continuation import agent_default_continuation_mode
from sase.tool.executor_display import warn_once
from sase.tool.executor_models import RecordedRunContext, ToolRunCliRequest
from sase.tool.executor_recording import begin_tool_run
from sase.tool.executor_run import run_recorded_body
from sase.tool.executor_signals import SignalState
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.logs import LogSinkError, prepare_run_paths
from sase.tool.observe import inc_tool_metric
from sase.tool.ownership import (
    ToolRunOwnerConflict,
    ToolRunOwnership,
    compact_requested,
    resolve_ownership,
)

# tools/_run_silent_record.py appends JSONL; this executor only tails and ingests.

_WARN_NOT_RECORDED = "sase: run not recorded"


def execute_tool_run(request: ToolRunCliRequest) -> int:
    """Run one named or ad-hoc command and return the child-or-signal exit."""

    if request.keep_going and request.fail_fast:
        print(
            "-k/--keep-going and -x/--fail-fast cannot be used together",
            file=sys.stderr,
        )
        return 2
    if request.hand_off and request.detach:
        print(
            "-H/--hand-off and -d/--detach cannot be used together",
            file=sys.stderr,
        )
        return 2
    if request.detach:
        from sase.tool.detach import execute_detached

        return execute_detached(request)
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
    # Ceiling refusal runs before any reconcile, reservation, or spawn: a
    # refused tool writes no ToolRun row and starts no child (exit 2).
    from sase.tool.routing import inline_refusal

    refusal = inline_refusal(resolved)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    # An agent with a sync budget escalates instead of running inline: the
    # detached run is followed inside the budget, and a start failure falls
    # through to the inline body below with a new id.
    from sase.tool.inline_escalation import try_inline_escalation

    escalated = try_inline_escalation(
        request,
        resolved=resolved,
        continuation_mode=continuation_mode,
        compact=compact,
    )
    if escalated is not None:
        return escalated
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

    # A foreground run is bounded by the caller's own harness, so the
    # starter records its provider and ceilings; the body writes them right
    # after the spawn. Nothing known means no write.
    foreground_demand = build_demand_context(os.environ) if recorded else None
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
        demand_context=foreground_demand,
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


def _recorded_agent_attribution() -> str:
    """Return the agent name this run would record, or an empty string.

    This mirrors the attribution ``build_begin_request`` persists: the
    foreground ``SASE_AGENT_NAME``, or ``SASE_TOOL_RUN_AGENT`` for an
    E1.5-wrapped run inside a monitor-owned proc.
    """

    return (os.environ.get("SASE_AGENT_NAME") or "").strip() or (
        os.environ.get("SASE_TOOL_RUN_AGENT") or ""
    ).strip()


def _continuation_mode(
    request: ToolRunCliRequest, resolved: ResolvedToolArgv
) -> str | None:
    """Validate continuation controls and choose the child handshake mode."""

    default_mode = default_continuation_mode(resolved)
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


__all__ = ["execute_tool_run"]
