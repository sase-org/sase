"""Inline-then-escalate: an agent's plain ``sase tool run`` escalates.

When the ``tool_run_escalation`` flag is on and the provider reports a sync
wait budget, an agent's plain ``sase tool run`` (no ``-H``, no ``--detach``,
no live owner, no parent run) starts the run detached through the shared
hand-off submission and follows it inline. A run that settles inside the
budget renders the inline-identical result; at the budget or on a signal the
follower prints the shared escalation block and exits without stopping the
run. Anything that cannot start falls back to today's inline run by
returning ``None``; a launched run is never rerun.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.tool.detach import enclosing_owner, escalation_enabled, parent_run
from sase.tool.follow_run import follow_run
from sase.tool.starter import resolve_starter

if TYPE_CHECKING:
    from sase.tool.argv import ResolvedToolArgv
    from sase.tool.executor import ToolRunCliRequest

#: Exact fail-open warning when the escalating path cannot start.
_UNAVAILABLE_PREFIX = "sase: inline escalation unavailable"

#: At most how long the follower waits for the owner proc to go terminal
#: before rendering the settled footer from whatever the ledger has.
_PROC_WAIT_SECONDS = 10.0
_PROC_WAIT_POLL_SECONDS = 0.2

_SIGNAL_EXITS: dict[int, int] = {
    int(signal.SIGTERM): 143,
    int(signal.SIGINT): 130,
    int(signal.SIGHUP): 129,
}


def try_inline_escalation(
    request: ToolRunCliRequest,
    *,
    resolved: ResolvedToolArgv,
    continuation_mode: str | None,
    compact: bool,
) -> int | None:
    """Start detached and follow inside the sync budget, or return ``None``.

    ``None`` is the only fail-open result: the caller falls through to
    today's inline run with a new id. A launched run never reruns — an
    unexpected follow error surfaces and returns ``1``.
    """

    if request.hand_off or request.detach:
        return None
    if not escalation_enabled():
        return None
    if not (os.environ.get("SASE_AGENT") or "").strip():
        return None
    if enclosing_owner() is not None:
        return None
    if parent_run() is not None:
        return None
    from sase.tool.routing import sync_wait_budget

    budget = sync_wait_budget()
    if budget is None:
        return None
    budget_seconds = budget.get("budget_seconds")
    if type(budget_seconds) is not int or budget_seconds <= 0:
        return None
    return _start_and_follow(
        request,
        resolved=resolved,
        continuation_mode=continuation_mode,
        compact=compact,
        budget=dict(budget),
        budget_seconds=budget_seconds,
    )


def _start_and_follow(
    request: ToolRunCliRequest,
    *,
    resolved: ResolvedToolArgv,
    continuation_mode: str | None,
    compact: bool,
    budget: dict[str, Any],
    budget_seconds: int,
) -> int | None:
    from sase.tool.handoff_launch import submit_handoff_run
    from sase.tool.liveness import reconcile_unsettled_tool_runs

    reconcile_unsettled_tool_runs(reap_orphans=True)

    resolution = resolve_starter()
    if not resolution.resolved or resolution.starter is None:
        _warn_unavailable(resolution.reason or "unknown reason")
        return None
    starter = resolution.starter

    submitted = submit_handoff_run(
        resolved,
        launch_root=Path.cwd(),
        agent=str(starter.get("agent") or ""),
        starter=starter,
        continuation_mode=continuation_mode,
        detached=True,
    )
    reservation = submitted.reservation
    if not reservation.reserved:
        _warn_unavailable(reservation.error or "reservation failed")
        return None
    if submitted.submit_error is not None:
        _warn_unavailable(submitted.submit_error)
        return None

    run_id = reservation.run_id
    from sase.tool.executor_display import write_display

    write_display(sys.stderr, f"sase tool run {run_id}\n".encode())

    stop_event = threading.Event()
    first_signal: list[int] = []

    def _record(signum: int, _frame: object) -> None:
        if not first_signal:
            first_signal.append(int(signum))
        stop_event.set()

    previous_term = signal.signal(signal.SIGTERM, _record)
    previous_int = signal.signal(signal.SIGINT, _record)
    previous_hup = signal.signal(signal.SIGHUP, _record)
    try:
        try:
            outcome = follow_run(
                run_id,
                deadline_s=float(budget_seconds),
                stream_output=not compact,
                compact=compact,
                stop_event=stop_event,
            )
        except Exception as exc:  # noqa: BLE001 - a launched run never reruns.
            print(
                f"sase: inline escalation follow failed for {run_id} "
                f"({exc}); the run was not stopped",
                file=sys.stderr,
            )
            return 1
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGHUP, previous_hup)

    if outcome.kind == "settled" and outcome.envelope is not None:
        run = outcome.envelope.get("run")
        stages = outcome.envelope.get("stages")
        if isinstance(run, dict):
            return _render_settled(
                run_id,
                run,
                stages=stages,
                compact=compact,
                tail_lines=request.tail_lines,
                stop_event=stop_event,
            )
    from sase.tool.control import UNSETTLED_RUN_STATES

    current = _current_envelope(run_id, fallback=outcome.envelope)
    run = current.get("run") if isinstance(current, dict) else None
    if (
        isinstance(run, dict)
        and str(run.get("state") or "") not in UNSETTLED_RUN_STATES
    ):
        stages = current.get("stages") if isinstance(current, dict) else None
        return _render_settled(
            run_id,
            run,
            stages=stages,
            compact=compact,
            tail_lines=request.tail_lines,
            stop_event=stop_event,
        )
    if outcome.kind == "stopped":
        code = _SIGNAL_EXITS.get(
            first_signal[0] if first_signal else int(signal.SIGTERM), 143
        )
    else:
        code = 124
    _print_escalation_block(run_id, current, budget)
    return code


def _warn_unavailable(why: str) -> None:
    print(f"{_UNAVAILABLE_PREFIX} ({why}); running inline", file=sys.stderr)


def _current_envelope(
    run_id: str, *, fallback: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the current show envelope for the escalation block or footer."""

    try:
        from sase.core.tool_run import tool_run_show

        envelope = tool_run_show(run_id)
    except Exception:  # noqa: BLE001 - the fallback still describes the run.
        return fallback
    if isinstance(envelope, dict) and isinstance(envelope.get("run"), dict):
        return envelope
    return fallback


def _print_escalation_block(
    run_id: str,
    envelope: dict[str, Any] | None,
    budget: dict[str, Any],
) -> None:
    from sase.tool.routing import escalation_block

    run = envelope.get("run") if isinstance(envelope, dict) else None
    if not isinstance(run, dict):
        run = {"run_id": run_id, "state": "running"}
    print(escalation_block(run, budget, run_id), file=sys.stderr)


def _settled_exit(run: dict[str, Any]) -> int:
    """Map a settled show run to the process exit of the inline footer."""

    exit_code = run.get("exit_code")
    if type(exit_code) is int:
        return exit_code
    if str(run.get("terminal_cause") or "") == "stop_requested":
        return 143
    if str(run.get("state") or "") == "signaled":
        return 143
    if str(run.get("state") or "") == "lost":
        return 1
    return 1


def _wait_for_owner_proc(run: dict[str, Any], stop_event: threading.Event) -> None:
    """Wait briefly for the owner proc to go terminal after the run settles.

    The run row becomes terminal inside ``finish_tool_run``, before triage
    and the receipt; the proc exiting is what means those have been
    written. A signal during this wait still returns the mapped exit.
    """

    owner_id = str(run.get("owner_id") or "")
    if not owner_id:
        return
    try:
        from sase.procs import TERMINAL_PROC_STATUSES
        from sase.procs.store import get_proc
    except Exception:  # noqa: BLE001 - render from whatever the ledger has.
        return
    deadline = time.monotonic() + _PROC_WAIT_SECONDS
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return
        try:
            proc = get_proc(owner_id)
        except Exception:  # noqa: BLE001 - the ledger is enough.
            return
        if proc is None or proc.status in TERMINAL_PROC_STATUSES:
            return
        time.sleep(_PROC_WAIT_POLL_SECONDS)


def _render_settled(
    run_id: str,
    run: dict[str, Any],
    *,
    stages: object,
    compact: bool,
    tail_lines: int,
    stop_event: threading.Event,
) -> int:
    _wait_for_owner_proc(run, stop_event)
    state = str(run.get("state") or "")
    mapped = _settled_exit(run)
    duration_ms = run.get("duration_ms")
    from sase.tool._query_shared import show_triage
    from sase.tool.executor_display import ledger_tail_text, write_run_footer
    from sase.tool.logs import truncation_message_lines

    triage = show_triage(run_id)
    truncation = truncation_message_lines(run.get("diagnostics"))
    tail = (
        ledger_tail_text(run, tail_lines)
        if state != "succeeded" and tail_lines > 0
        else ""
    )
    if isinstance(stages, (list, tuple)):
        stage_list: list[dict[str, Any]] = [
            item for item in stages if isinstance(item, dict)
        ]
    else:
        stage_list = []
    write_run_footer(
        durable_id=run_id,
        state=state,
        exit_code=mapped,
        duration_ms=duration_ms if type(duration_ms) is int else 0,
        compact=compact,
        tail_lines=tail_lines,
        stdout_sink=None,
        stderr_sink=None,
        stages=stage_list,
        truncation=truncation,
        triage=triage if isinstance(triage, dict) else None,
        triage_enabled=True,
        tail_text=tail,
    )
    return mapped


__all__ = ["try_inline_escalation"]
