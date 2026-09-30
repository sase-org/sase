"""Hidden join worker: follow a detached ToolRun into a monitor's log.

``sase tool _join RUN`` runs as a joining monitor's proc. It reasserts the
monitor's Rust join as an idempotent replay, streams the run's output of
record and stage lines into the monitor log without a deadline, then
renders a compact summary with the existing triage footer and mirrors the
run's mapped exit code. The joined run's executing proc stays the owner;
this worker never settles the run itself.

On SIGTERM/SIGINT the worker asks the run's owner to stop — with a reason
naming the joining monitor — waits at most 15 seconds, then exits 143/130.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Any

#: Seconds a signaled join worker waits for the run to settle before exiting.
_STOP_SETTLE_WAIT_SECONDS = 15.0


def join_worker_argv(run_id: str) -> list[str]:
    """Return the monitor proc argv that follows *run_id* into the log."""

    return [sys.executable, "-m", "sase", "tool", "_join", run_id]


def _mapped_exit_code(run: dict[str, Any]) -> int:
    """Return the CLI exit code a settled *run* maps to.

    A recorded exit code wins; otherwise a signal maps to ``128+signal``,
    a requested stop maps to ``143`` (the ledger row carries no code), and
    anything else (``lost``, ``interrupt``, ``timeout`` without a code) is
    ``1``.
    """

    exit_code = run.get("exit_code")
    if type(exit_code) is int:
        return exit_code
    sig = run.get("signal")
    if type(sig) is int:
        return 128 + sig
    if str(run.get("terminal_cause") or "") == "stop_requested":
        return 143
    return 1


def execute_join_run(run_id: str) -> int:
    """Follow *run_id* into this monitor's log until it settles."""

    run_id = (run_id or "").strip()
    if not run_id:
        print("Usage: sase tool _join RUN", file=sys.stderr)
        return 2
    monitor_id = (os.environ.get("SASE_MONITOR_ID") or "").strip()
    if not monitor_id:
        print(
            "sase tool _join: no joining monitor in the environment; run nothing",
            file=sys.stderr,
        )
        return 2

    refusal = _reassert_join(run_id, monitor_id)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 1

    stop_event = threading.Event()
    received: list[int] = []
    previous_int = signal.signal(
        signal.SIGINT, _make_handler(signal.SIGINT, stop_event, received)
    )
    previous_term = signal.signal(
        signal.SIGTERM, _make_handler(signal.SIGTERM, stop_event, received)
    )
    try:
        from sase.tool.follow_run import follow_run

        outcome = follow_run(run_id, stop_event=stop_event)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)

    if outcome.kind == "stopped":
        signum = received[0] if received else signal.SIGTERM
        _request_owner_stop(run_id, monitor_id)
        _wait_for_settlement(run_id)
        return 130 if signum == signal.SIGINT else 143
    envelope = outcome.envelope
    run = envelope.get("run") if isinstance(envelope, dict) else None
    if not isinstance(run, dict):
        print(f"sase tool _join: tool run {run_id} was not found", file=sys.stderr)
        return 1
    code = _mapped_exit_code(run)
    _render_compact_summary(run_id, run, code)
    return code


def _reassert_join(run_id: str, monitor_id: str) -> str | None:
    """Reassert this monitor's join; return an error message or ``None``.

    The same monitor rejoining is an idempotent replay and proceeds. A run
    that settled between validation and this replay still proceeds: the
    follow below returns at once and renders its summary. Every other
    refusal stops the worker with exit ``1``.
    """

    from sase.core.tool_run import tool_run_join

    requested_by = (
        (os.environ.get("SASE_AGENT_NAME") or "").strip()
        or (os.environ.get("SASE_TOOL_RUN_AGENT") or "").strip()
        or f"monitor:{monitor_id}"
    )
    join_request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "joiner_kind": "monitor",
        "joiner_id": monitor_id,
        "requested_by": requested_by,
    }
    try:
        result = tool_run_join(join_request)
    except Exception as exc:  # noqa: BLE001 - never follow without a join.
        return f"sase tool _join: could not join tool run {run_id} ({exc})"
    if not isinstance(result, dict):
        return f"sase tool _join: could not join tool run {run_id} (no result)"
    if result.get("outcome") == "joined":
        return None
    if result.get("refusal") == "settled":
        return None
    refusal = str(result.get("refusal") or "refused")
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    state = str(run.get("state") or "") if isinstance(run, dict) else ""
    detail = f"state {state}; " if state else ""
    return (
        f"sase tool _join: tool run {run_id} cannot be joined "
        f"({detail}refusal {refusal}); sase tool show {run_id}"
    )


def _make_handler(signum: int, event: threading.Event, received: list[int]):  # type: ignore[no-untyped-def]
    def _handler(_signum: object, _frame: object) -> None:
        if not received:
            received.append(signum)
        event.set()

    return _handler


def _request_owner_stop(run_id: str, monitor_id: str) -> None:
    """Ask the run's owner to stop with a reason naming this monitor."""

    from sase.procs.runtime import read_termination_intent
    from sase.tool.control_stop import stop_run_through_owner

    proc_id = (os.environ.get("SASE_PROC_ID") or "").strip() or monitor_id
    try:
        intent = read_termination_intent(proc_id)
    except Exception:  # noqa: BLE001 - an unreadable intent is a plain stop.
        intent = None
    if intent in ("total-timeout", "idle-timeout"):
        reason = f"joining monitor {monitor_id} timed out ({intent})"
    else:
        reason = f"joining monitor {monitor_id} stopped"
    try:
        stop_run_through_owner(run_id, requested_by="sase", reason=reason)
    except Exception:  # noqa: BLE001 - the wait below still bounds the exit.
        pass


def _wait_for_settlement(run_id: str) -> None:
    """Wait for *run_id* to settle, at most 15 seconds."""

    from sase.core.tool_run import tool_run_show

    deadline = time.monotonic() + _STOP_SETTLE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            shown = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - a transient read retries.
            time.sleep(0.2)
            continue
        run = shown.get("run") if isinstance(shown, dict) else None
        if not isinstance(run, dict):
            return
        if str(run.get("state") or "") not in ("created", "running"):
            return
        time.sleep(0.2)


def _render_compact_summary(run_id: str, run: dict[str, Any], code: int) -> None:
    """Render the compact settlement summary plus the triage footer."""

    from sase.tool._query_shared import show_triage
    from sase.tool.triage_display import footer_triage_lines

    state = str(run.get("state") or "unknown")
    duration = run.get("duration_ms")
    duration_text = f"{duration}ms" if type(duration) is int else "—"
    line = state
    if code:
        line += f"/{code}"
    print(f"{line}  {duration_text}", file=sys.stderr)
    triage = show_triage(run_id)
    lines, verdict = footer_triage_lines(
        triage if isinstance(triage, dict) else None, exit_code=code
    )
    for triage_line in lines:
        print(triage_line, file=sys.stderr)
    print(f"sase tool show {run_id} -l", file=sys.stderr)
    if verdict is not None:
        print(verdict, file=sys.stderr)


__all__ = ["execute_join_run", "join_worker_argv"]
