"""Wrapper liveness observation and lost-run reconciliation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.core.process_identity import (
    identity_from_previous_boot,
    process_identity_token,
)
from sase.core.tool_run import tool_run_list, tool_run_reconcile


_LOST_REASON = "runner exited without settling"
_UNSETTLED_STATES = ("created", "running")
_RECONCILE_LIMIT = 1000


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


def reconcile_unsettled_tool_runs() -> dict[str, Any]:
    """Collect bounded liveness facts and persist lost transitions."""

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
            if isinstance(run, dict):
                facts.append(_observe_wrapper(run))
    if not facts and not diagnostics:
        try:
            return tool_run_reconcile({"schema_version": 1, "facts": []})
        except Exception as exc:  # noqa: BLE001 - missing store is not fatal.
            return {
                "schema_version": 1,
                "marked_lost": [],
                "persisted": False,
                "diagnostics": [str(exc)],
            }
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
    return result


__all__ = [
    "current_boot_id",
    "reconcile_unsettled_tool_runs",
]
