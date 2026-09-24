"""Owner observation for hand-off ToolRuns: reconcile facts and retention."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

_OWNER_KINDS = frozenset({"proc", "monitor"})
_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1


def _owner_ref(run: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return ``(kind, id)`` for a proc- or monitor-owned run, else ``None``."""

    kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    if kind not in _OWNER_KINDS or not owner_id:
        return None
    return kind, owner_id


def _wire_exit_code(value: object) -> int | None:
    if type(value) is int and _I32_MIN <= value <= _I32_MAX:
        return value
    return None


def _terminal_fact(
    kind: str,
    owner_id: str,
    *,
    exit_code: object,
    termination_reason: object,
    stop_requested: bool,
) -> dict[str, Any]:
    from sase.procs.runtime import read_termination_intent

    fact: dict[str, Any] = {"kind": kind, "id": owner_id, "state": "terminal"}
    code = _wire_exit_code(exit_code)
    if code is not None:
        fact["exit_code"] = code
    if isinstance(termination_reason, str) and termination_reason:
        fact["termination_reason"] = termination_reason
    fact["stop_requested"] = stop_requested or (
        read_termination_intent(owner_id) == "stop"
    )
    return fact


def observe_owner_fact(run: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the owner fact reconcile needs for one hand-off run.

    Only hand-off runs owned by a proc or monitor get a fact: foreground and
    nested runs keep their wrapper-only reconcile path. Monitor rows share the
    proc id, so both kinds read the proc store.
    """

    if str(run.get("launch_mode") or "") != "handoff":
        return None
    ref = _owner_ref(run)
    if ref is None:
        return None
    kind, owner_id = ref
    try:
        from sase.procs.models import TERMINAL_PROC_STATUSES
        from sase.procs.store import get_proc

        proc = get_proc(owner_id)
        if proc is None:
            return {"kind": kind, "id": owner_id, "state": "missing"}
        if proc.status not in TERMINAL_PROC_STATUSES:
            return {"kind": kind, "id": owner_id, "state": "active"}
        result = proc.result if isinstance(proc.result, dict) else {}
        return _terminal_fact(
            kind,
            owner_id,
            exit_code=proc.exit_code,
            termination_reason=result.get("termination_reason"),
            stop_requested=bool(proc.stop_requested_at),
        )
    except Exception:  # noqa: BLE001 - an unreadable owner is never proof.
        return {"kind": kind, "id": owner_id, "state": "unknown"}


def owner_fact_from_settlement(
    kind: str, owner_id: str, state: Mapping[str, Any]
) -> dict[str, Any]:
    """Build a terminal owner fact from a proc settlement ``state`` dict.

    Settlement runs before the proc row is finished, so the row still reads
    ``settling`` (active); the hooks pass the outcome they already hold.
    """

    return _terminal_fact(
        kind,
        owner_id,
        exit_code=state.get("exit_code"),
        termination_reason=state.get("termination_reason"),
        stop_requested=bool(state.get("stop_requested")),
    )


def owner_retention(run: Mapping[str, Any]) -> dict[str, Any]:
    """Report whether a run's owner row and log are still retained."""

    logs = run.get("logs")
    recorded = logs.get("owner_log_path") if isinstance(logs, dict) else None
    ref = _owner_ref(run)
    if ref is None:
        return {"owner": "none", "log": "none", "log_path": None}
    kind, owner_id = ref
    owner = "unknown"
    live_log: str | None = None
    try:
        from sase.procs.store import get_proc

        proc = get_proc(owner_id)
    except Exception:  # noqa: BLE001 - retention is best-effort reporting.
        pass
    else:
        if proc is None:
            owner = "pruned"
        else:
            owner = "retained"
            live_log = proc.log_path or None
    path: str | None = str(recorded) if recorded else live_log
    if path is None and kind == "monitor":
        from sase.tool.control import monitor_output_path

        found = monitor_output_path(dict(run), owner_id)
        path = str(found) if found is not None else None
    if path is None:
        return {"owner": owner, "log": "not-recorded", "log_path": None}
    log = "retained" if Path(path).is_file() else "missing"
    return {"owner": owner, "log": log, "log_path": path}


__all__ = [
    "observe_owner_fact",
    "owner_fact_from_settlement",
    "owner_retention",
]
