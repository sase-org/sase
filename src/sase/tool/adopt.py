"""Hidden adopting worker: claim a reserved hand-off run, then run it."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_claim, tool_run_show
from sase.procs.runtime import read_termination_intent
from sase.tool.executor import RecordedRunContext, run_recorded_body
from sase.tool.executor_signals import SignalState
from sase.tool.handoff import resolved_from_envelope
from sase.tool.liveness import current_boot_id

_TIMEOUT_INTENTS = frozenset({"total-timeout", "idle-timeout"})


def execute_adopted_run(run_id: str) -> int:
    """Claim *run_id* for the enclosing owner and run its frozen argv."""

    owner_kind: str | None = None
    owner_id: str | None = None
    monitor_id = (os.environ.get("SASE_MONITOR_ID") or "").strip()
    proc_id = (os.environ.get("SASE_PROC_ID") or "").strip()
    if monitor_id:
        owner_kind = "monitor"
        owner_id = monitor_id
    elif proc_id:
        owner_kind = "proc"
        owner_id = proc_id
    if owner_kind is None or owner_id is None:
        print(
            "sase tool _adopt: no owner in the environment; run nothing",
            file=sys.stderr,
        )
        return 2

    signals = SignalState()
    previous_int = signal.signal(signal.SIGINT, signals.handler)
    previous_term = signal.signal(signal.SIGTERM, signals.handler)
    try:
        return _claim_and_run(run_id, owner_kind, owner_id, signals)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def _claim_and_run(
    run_id: str, owner_kind: str, owner_id: str, signals: SignalState
) -> int:
    pid = os.getpid()
    # The supervisor sets SASE_PROC_ID for monitor procs too, and a monitor's
    # proc id is its monitor id, so the termination intent is always keyed by it.
    proc_id = (os.environ.get("SASE_PROC_ID") or "").strip() or owner_id
    identity = process_identity_token(pid)
    boot_id, _, _ = identity.partition(":") if identity else ("", "", "")
    owner_log = (os.environ.get("SASE_PROC_LOG_PATH") or "").strip() or None
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "wrapper_pid": pid,
        "boot_id": boot_id or current_boot_id() or None,
        "process_start_identity": identity or None,
    }
    if owner_log is not None:
        request["owner_log_path"] = owner_log
    try:
        result = tool_run_claim(request)
    except Exception as exc:  # noqa: BLE001 - never run without a claim.
        print(f"sase tool _adopt: claim failed for {run_id} ({exc})", file=sys.stderr)
        return 1

    outcome = str(result.get("outcome") or "")
    if outcome == "stopped":
        print(
            f"sase tool _adopt: run {run_id} was stopped before it started; "
            "command was not run",
            file=sys.stderr,
        )
        return 143
    if outcome != "claimed":
        refusal = str(result.get("refusal") or "refused")
        print(
            f"sase tool _adopt: claim refused for {run_id} ({refusal}); "
            "command was not run",
            file=sys.stderr,
        )
        return 2

    launch = result.get("launch")
    if not isinstance(launch, dict):
        print(
            f"sase tool _adopt: claim refused for {run_id} (missing launch); "
            "command was not run",
            file=sys.stderr,
        )
        return 2
    resolved = resolved_from_envelope(launch)
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    logs = run.get("logs") if isinstance(run, dict) else None
    events_raw = logs.get("events_path") if isinstance(logs, dict) else None
    events_path = Path(str(events_raw)) if events_raw else None
    # The worker inherits the reservation's recorded attribution — the
    # starter agent for a monitor reservation — so an agent-attributed
    # run defaults to known-gated continuation behind the flag.
    recorded_agent = ""
    if isinstance(run, dict):
        recorded_agent = str(run.get("agent") or "").strip()

    from sase.tool.executor import agent_default_continuation_mode

    envelope_mode = (
        launch.get("continuation_mode") if isinstance(launch, dict) else None
    )
    if envelope_mode in ("always", "never", "known"):
        continuation_mode = envelope_mode
    else:
        continuation_mode = agent_default_continuation_mode(resolved, recorded_agent)
    starter = run.get("starter") if isinstance(run, dict) else None
    if isinstance(starter, dict) and starter:
        _start_starter_watchdog(run_id, dict(starter))

    ctx = RecordedRunContext(
        run_id=run_id,
        recorded=True,
        resolved=resolved,
        has_owner=True,
        owns_output=False,
        compact=False,
        tail_lines=200,
        events_path=events_path,
        stdout_path=None,
        stderr_path=None,
        stop_recorded=_stop_probe(run_id, owner_kind, owner_id, proc_id),
        timeout_recorded=_timeout_probe(proc_id),
        continuation_mode=continuation_mode,
    )
    code = run_recorded_body(ctx, signals)
    if owner_kind == "proc":
        _deliver_settlement(run_id)
    return code


#: Seconds between starter-liveness polls for starter-scoped runs.
_WATCHDOG_POLL_SECONDS = 5.0


def _start_starter_watchdog(run_id: str, starter: dict[str, Any]) -> None:
    """Watch a starter-scoped run's starter; stop the run when it is gone.

    While the starter identity is live the run is left alone. Once the
    starter is gone the run survives only while its join names an active
    monitor; otherwise a stop is requested (``requested_by: sase``) and
    routed through the same owner path ``sase tool stop`` uses. The thread
    is a daemon and best effort: it never raises and never blocks exit.
    """

    thread = threading.Thread(
        target=_watch_starter,
        args=(run_id, starter),
        name=f"sase-starter-watchdog-{run_id[:8]}",
        daemon=True,
    )
    thread.start()


def _watch_starter(run_id: str, starter: dict[str, Any]) -> None:
    from sase.tool.starter import starter_alive

    try:
        while True:
            try:
                alive = starter_alive(starter)
            except Exception:  # noqa: BLE001 - an unread check leaves the run alone.
                alive = True
            if alive:
                time.sleep(_WATCHDOG_POLL_SECONDS)
                continue
            try:
                shown = tool_run_show(run_id)
            except Exception:  # noqa: BLE001 - an unreadable run ends the watch.
                return
            run = shown.get("run") if isinstance(shown, dict) else None
            if not isinstance(run, dict):
                return
            if str(run.get("state") or "") not in ("created", "running"):
                return
            join_id = _active_join_monitor_id(run)
            if join_id is not None:
                # The starter is gone but a live monitor owns the follow-up:
                # keep watching in case that monitor ends first.
                time.sleep(_WATCHDOG_POLL_SECONDS)
                continue
            join = run.get("join") if isinstance(run.get("join"), dict) else None
            if isinstance(join, dict) and str(join.get("id") or ""):
                reason = f"joining monitor {join.get('id')} ended"
            else:
                agent = (
                    str(starter.get("agent") or "").strip()
                    or str(run.get("agent") or "").strip()
                )
                reason = f"starter agent {agent} ended without joining"
            from sase.tool.control_stop import stop_run_through_owner

            stop_run_through_owner(run_id, requested_by="sase", reason=reason)
            return
    except Exception:  # noqa: BLE001 - the watchdog never raises.
        return


def _active_join_monitor_id(run: dict[str, Any]) -> str | None:
    """Return the joined monitor id when it names an active monitor."""

    from sase.tool.detach_cleanup import joined_monitor_active

    return joined_monitor_active(run)


def _deliver_settlement(run_id: str) -> None:
    """Publish the once-only settlement notification; never changes the exit."""

    try:
        from sase.tool.notify import deliver_handoff_settlement

        deliver_handoff_settlement(run_id)
    except Exception:  # noqa: BLE001 - delivery is best effort.
        pass


def _timeout_probe(proc_id: str):  # type: ignore[no-untyped-def]
    def _probe() -> bool:
        return read_termination_intent(proc_id) in _TIMEOUT_INTENTS

    return _probe


def _stop_probe(run_id: str, owner_kind: str, owner_id: str, proc_id: str):  # type: ignore[no-untyped-def]
    def _probe() -> bool:
        intent = read_termination_intent(proc_id)
        if intent == "stop":
            return True
        if intent in _TIMEOUT_INTENTS:
            # The owner's first recorded intent wins: a timeout is not a stop.
            return False
        try:
            shown = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - unknown stop never blocks execution.
            shown = {}
        run = shown.get("run") if isinstance(shown, dict) else None
        if isinstance(run, dict) and run.get("stop_request") is not None:
            return True
        if owner_kind == "proc":
            try:
                from sase.procs.store import get_proc

                proc = get_proc(owner_id)
            except Exception:  # noqa: BLE001 - unknown owner never stops a run.
                return False
            return proc is not None and proc.stop_requested_at is not None
        return False

    return _probe


__all__ = ["execute_adopted_run"]
