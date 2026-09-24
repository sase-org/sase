"""Hidden adopting worker: claim a reserved hand-off run, then run it."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_claim, tool_run_show
from sase.tool.executor import RecordedRunContext, run_recorded_body
from sase.tool.executor_signals import SignalState
from sase.tool.handoff import resolved_from_envelope
from sase.tool.liveness import current_boot_id
from sase.tool.ownership import ToolRunOwnership


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

    ownership = ToolRunOwnership(
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=None,
        other_owner_kind=None,
        other_owner_id=None,
        owns_output=False,
        enclosing_label=f"{owner_kind} {owner_id}",
    )
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
        stop_recorded=_stop_probe(run_id, owner_kind, owner_id),
    )
    # The worker owns the lifecycle of its claimed run, so it reaps
    # identity-matched survivors the same way the foreground path does.
    # Reaping is handled inside the shared body path via reconcile in the
    # caller; the worker itself just runs the body.
    _ = ownership
    return run_recorded_body(ctx, signals)


def _stop_probe(run_id: str, owner_kind: str, owner_id: str):  # type: ignore[no-untyped-def]
    def _probe() -> bool:
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
