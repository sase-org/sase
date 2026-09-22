"""Wrapper liveness observation and lost-run reconciliation."""

from __future__ import annotations

import os
import signal
from pathlib import Path
import time
from typing import Any

from sase.core.process_identity import (
    identity_from_previous_boot,
    process_identity_token,
)
from sase.core.tool_run import tool_run_list, tool_run_reconcile
from sase.tool.stage_protocol import ingest_event_file


_LOST_REASON = "runner exited without settling"
_UNSETTLED_STATES = ("created", "running")
_RECONCILE_LIMIT = 1000
_REAP_TERM_GRACE_SECONDS = 2.0
_REAP_POLL_SECONDS = 0.05


def current_boot_id() -> str:
    """Return the current kernel boot id, or ``""`` when unavailable."""

    try:
        return (
            Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        )
    except OSError:
        token = process_identity_token(os.getpid())
        return token.partition(":")[0]


def _observe_wrapper(run: dict[str, Any]) -> dict[str, Any]:
    """Return a core liveness fact for one unsettled wrapper."""

    run_id = str(run.get("run_id") or "")
    pid_raw = run.get("wrapper_pid")
    recorded = run.get("process_start_identity")
    recorded_boot = str(run.get("boot_id") or "")
    fact: dict[str, Any] = {
        "run_id": run_id,
        "wrapper_pid": pid_raw,
        "boot_id": run.get("boot_id"),
        "process_start_identity": recorded,
    }
    if pid_raw is None:
        fact["observation"] = "unknown"
        fact["reason"] = "wrapper pid was not recorded"
        return fact
    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        fact["observation"] = "unknown"
        fact["reason"] = "wrapper pid is not an integer"
        return fact

    if recorded_boot:
        boot = current_boot_id()
        if boot and recorded_boot != boot:
            fact["observation"] = "dead"
            fact["reason"] = _LOST_REASON
            return fact
    if identity_from_previous_boot(recorded):
        fact["observation"] = "dead"
        fact["reason"] = _LOST_REASON
        return fact

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        fact["observation"] = "dead"
        fact["reason"] = _LOST_REASON
        return fact
    except PermissionError:
        fact["observation"] = "unknown"
        fact["reason"] = "wrapper liveness is permission-denied"
        return fact
    except OSError:
        fact["observation"] = "unknown"
        fact["reason"] = "wrapper liveness is unavailable"
        return fact

    current = process_identity_token(pid)
    if isinstance(recorded, str) and recorded and current and current != recorded:
        fact["observation"] = "dead"
        fact["reason"] = _LOST_REASON
        return fact
    if isinstance(recorded, str) and recorded and not current:
        fact["observation"] = "unknown"
        fact["reason"] = "wrapper identity is unreadable"
        return fact
    fact["observation"] = "alive"
    return fact


def _events_path(run: dict[str, Any]) -> Path | None:
    logs = run.get("logs")
    if not isinstance(logs, dict):
        return None
    raw = logs.get("events_path")
    if not raw:
        return None
    return Path(str(raw))


def reconcile_unsettled_tool_runs(*, reap_orphans: bool = False) -> dict[str, Any]:
    """Collect bounded liveness facts and persist lost transitions.

    Reconcile authorizes reap candidates (a recorded pgid plus the recorded
    child identity) for runs whose wrapper is definitively dead, but Rust
    never signals. Only the executor passes ``reap_orphans=True``: read-only
    store paths (``tool runs``, ``tool show``) reconcile without reaping and
    never signal a group.
    """

    facts: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for state in _UNSETTLED_STATES:
        try:
            listed = tool_run_list(
                {
                    "schema_version": 1,
                    "state": state,
                    "limit": _RECONCILE_LIMIT,
                }
            )
        except Exception as exc:  # noqa: BLE001 - queries must fail open.
            diagnostics.append(str(exc))
            continue
        diagnostics.extend(str(item) for item in listed.get("diagnostics") or ())
        for run in listed.get("runs") or ():
            if not isinstance(run, dict):
                continue
            events_path = _events_path(run)
            run_id = str(run.get("run_id") or "")
            if events_path is not None and run_id:
                diagnostics.extend(ingest_event_file(events_path, run_id))
            facts.append(_observe_wrapper(run))
    if not facts and not diagnostics:
        try:
            result = tool_run_reconcile({"schema_version": 1, "facts": []})
        except Exception as exc:  # noqa: BLE001 - missing store is not fatal.
            return {
                "schema_version": 1,
                "marked_lost": [],
                "persisted": False,
                "diagnostics": [str(exc)],
            }
        return _maybe_reap(result, reap_orphans=reap_orphans)
    try:
        result = tool_run_reconcile({"schema_version": 1, "facts": facts})
    except Exception as exc:  # noqa: BLE001 - read-only/busy must not crash.
        return {
            "schema_version": 1,
            "marked_lost": [],
            "persisted": False,
            "diagnostics": [*diagnostics, str(exc)],
        }
    merged = list(result.get("diagnostics") or ())
    merged.extend(diagnostics)
    result["diagnostics"] = list(dict.fromkeys(str(item) for item in merged))
    return _maybe_reap(result, reap_orphans=reap_orphans)


def _maybe_reap(result: dict[str, Any], *, reap_orphans: bool) -> dict[str, Any]:
    """Signal authorized reap candidates when the caller owns the lifecycle."""

    if not reap_orphans:
        return result
    candidates = result.get("reap_candidates") or ()
    reaped: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            reaped.append(_reap_authorized_candidate(candidate))
    if reaped:
        diagnostics = list(result.get("diagnostics") or ())
        diagnostics.extend(reaped)
        result["diagnostics"] = list(dict.fromkeys(str(item) for item in diagnostics))
    return result


def _reap_authorized_candidate(candidate: dict[str, Any]) -> str:
    """TERM-then-KILL one authorized group, or explain why it was spared.

    Only a candidate reconcile authorized is ever considered, and even then a
    PID-reuse mismatch, an unreadable identity, a permission error, a missing
    process, or our own process group is a diagnostic — never a signal.
    """

    run_id = str(candidate.get("run_id") or "")
    label = f"run {run_id}" if run_id else "run with no id"
    try:
        pgid = int(candidate.get("pgid"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"{label}: reap candidate pgid is not an integer; not signaling"
    if pgid <= 0:
        return f"{label}: reap candidate pgid {pgid} is invalid; not signaling"
    if pgid == os.getpgrp():
        return f"{label}: reap candidate is our own process group; not signaling"
    recorded = candidate.get("child_process_start_identity")
    if not isinstance(recorded, str) or not recorded:
        return f"{label}: child identity was not recorded; not signaling pgid {pgid}"
    try:
        current = process_identity_token(pgid)
    except Exception:  # noqa: BLE001 - identity reads are best effort.
        current = ""
    if not current:
        return (
            f"{label}: identity of pgid {pgid} is unreadable; not signaling "
            "(PID reuse is never proof)"
        )
    if current != recorded:
        return (
            f"{label}: identity of pgid {pgid} no longer matches the recorded "
            "child; not signaling (stale pgid, PID reuse?)"
        )
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return f"{label}: pgid {pgid} is already gone; nothing to reap"
    except PermissionError:
        return f"{label}: permission denied signaling pgid {pgid}; not signaling"
    except OSError as exc:
        return f"{label}: cannot signal pgid {pgid} ({exc}); not signaling"
    deadline = time.monotonic() + _REAP_TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, PermissionError):
            return f"{label}: reaped pgid {pgid} with SIGTERM"
        except OSError:
            return f"{label}: pgid {pgid} liveness is unavailable; not escalating"
        time.sleep(_REAP_POLL_SECONDS)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return f"{label}: reaped pgid {pgid} with SIGTERM"
    except OSError as exc:
        return f"{label}: cannot escalate pgid {pgid} ({exc}); not signaling"
    return f"{label}: reaped pgid {pgid} with SIGTERM then SIGKILL"


__all__ = [
    "current_boot_id",
    "reconcile_unsettled_tool_runs",
]
