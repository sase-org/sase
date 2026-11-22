"""Shared waiting-state copy for ToolRun admission surfaces.

Every user-facing surface that names the admission queue (``sase tool
runs`` and ``show``, ``wait`` and its escalation block, followers, the
monitor detail, and the TUI) reads through these helpers so the words,
the queue math, and the fail-open behavior agree. Nothing here writes
to the ledger: live queue positions come from read-only ``show``
envelopes and degrade to the stored record when the lookup fails.
"""

from __future__ import annotations

from typing import Any

from sase.tool.render import EMPTY, format_duration_ms

#: Stored-record and live-view state for a run still queued for a slot.
WAITING = "waiting"

#: Stored-record state for a run that held (or jumped) a slot.
ADMITTED = "admitted"

#: Stored-record state for a run that settled while still queued.
ABANDONED = "abandoned"


def stored_admission(run: Any) -> dict[str, Any] | None:
    """Return the run's stored ``demand.admission`` record, if any."""

    if not isinstance(run, dict):
        return None
    demand = run.get("demand")
    if not isinstance(demand, dict):
        return None
    admission = demand.get("admission")
    return admission if isinstance(admission, dict) else None


def live_admission_view(source: Any) -> dict[str, Any] | None:
    """Return the live admission view for a show envelope or run.

    A ``tool_run_show`` envelope carries the derived live view (with a
    fresh ``ahead``) at the top level; a bare run dict only carries the
    stored record. Prefer the live view and fall back to the stored
    record so settled runs still describe how they waited.
    """

    if not isinstance(source, dict):
        return None
    view = source.get("admission")
    if isinstance(view, dict) and str(view.get("state") or ""):
        return view
    run = source.get("run")
    if isinstance(run, dict):
        view = run.get("admission")
        if isinstance(view, dict) and str(view.get("state") or ""):
            return view
        return stored_admission(run)
    return stored_admission(source)


def _as_int(value: Any) -> int | None:
    if type(value) is bool:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def is_live_waiting(run: Any, view: Any = None) -> bool:
    """Return True when *run* is unsettled and still queued for a slot."""

    if not isinstance(run, dict):
        return False
    if str(run.get("state") or "") not in ("created", "running"):
        return False
    admission = view if isinstance(view, dict) else stored_admission(run)
    return isinstance(admission, dict) and str(admission.get("state") or "") == WAITING


def waiting_key(admission: Any) -> str:
    """Return the admission key (tool name) for copy, defaulting to ``check``."""

    if isinstance(admission, dict) and admission.get("key"):
        return str(admission["key"])
    return "check"


def waiting_ahead(view: Any, record: Any = None) -> int | None:
    """Return the live queue position, falling back to the stored request."""

    for source in (view, record):
        if isinstance(source, dict):
            ahead = _as_int(source.get("ahead"))
            if ahead is not None:
                return max(0, ahead)
    if isinstance(record, dict):
        ahead = _as_int(record.get("ahead_at_request"))
        if ahead is not None:
            return max(0, ahead)
    return None


def waiting_marker(ahead: int | None) -> str:
    """Return the ``runs`` STATE marker for a queued run."""

    if ahead is None:
        return "(waiting)"
    return f"(waiting, {ahead} ahead)"


def _format_wait_ms(wait_ms: Any) -> str:
    """Format a stored wait duration, ``EMPTY`` when absent."""

    if type(wait_ms) is bool or not isinstance(wait_ms, (int, float)):
        return EMPTY
    return format_duration_ms(max(0, int(wait_ms)))


def _format_since(requested_ts_ms: Any) -> str:
    from sase.core.time import format_local

    if type(requested_ts_ms) is bool or not isinstance(requested_ts_ms, (int, float)):
        return EMPTY
    return format_local(requested_ts_ms / 1000, "%H:%M", default=EMPTY)


def show_admission_line(run: dict[str, Any], live: Any = None) -> str | None:
    """Return the ``ADMISSION`` line for ``sase tool show``, if any.

    Live runs name the slot they wait for (or hold) with a fresh queue
    position; settled runs name how the wait ended. Runs that never
    queued render no line.
    """

    record = stored_admission(run)
    view = live if isinstance(live, dict) else None
    admission = view if view is not None else record
    if not isinstance(admission, dict):
        return None
    state = str(admission.get("state") or "")
    if state not in (WAITING, ADMITTED, ABANDONED):
        return None
    limit = _as_int(admission.get("limit"))
    limit_text = f"limit {limit}" if limit is not None else "limited"
    key = waiting_key(admission)
    if state == WAITING and is_live_waiting(run, admission):
        ahead = waiting_ahead(view, record)
        ahead_text = f"{ahead} ahead" if ahead is not None else "queued"
        since = _format_since(admission.get("requested_ts_ms"))
        return f"waiting for a {key} slot since {since} ({limit_text}, {ahead_text})"
    wait = _format_wait_ms(admission.get("wait_ms"))
    if state == ABANDONED:
        return f"abandoned after {wait} ({limit_text})"
    if str(admission.get("admitted_by") or "") == "max_wait":
        return f"admitted over limit after max wait ({limit_text})"
    return f"admitted after {wait} ({limit_text})"


def waiting_timeout_line(run_id: str, run: dict[str, Any]) -> str:
    """Return the ``wait``/escalation still-waiting line for a queued run."""

    record = stored_admission(run)
    key = waiting_key(record)
    ahead = waiting_ahead(None, record)
    if ahead is None and isinstance(run.get("run_id"), str):
        ahead = live_ahead(str(run.get("run_id") or ""))
    if ahead is not None:
        return f"tool run {run_id} is still waiting for a {key} slot ({ahead} ahead)"
    return f"tool run {run_id} is still waiting for a {key} slot"


def wait_json_admission(run: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``admission`` object for ``sase tool wait -j``."""

    record = stored_admission(run)
    if record is None:
        return None
    payload: dict[str, Any] = {
        "state": str(record.get("state") or ""),
        "key": waiting_key(record),
    }
    for field in (
        "limit",
        "seq",
        "requested_ts_ms",
        "admitted_ts_ms",
        "wait_ms",
        "admitted_by",
        "ahead_at_request",
    ):
        if record.get(field) is not None:
            payload[field] = record[field]
    if is_live_waiting(run, record) and isinstance(run.get("run_id"), str):
        ahead = live_ahead(str(run.get("run_id") or ""))
        if ahead is not None:
            payload["ahead"] = ahead
    elif waiting_ahead(None, record) is not None:
        payload["ahead"] = waiting_ahead(None, record)
    return payload


def live_ahead(run_id: str) -> int | None:
    """Return the live queue position for *run_id*, ``None`` on any failure."""

    if not run_id:
        return None
    try:
        from sase.core.tool_run import tool_run_show

        envelope = tool_run_show(run_id)
    except Exception:  # noqa: BLE001 - waiting copy never breaks the caller.
        return None
    if not isinstance(envelope, dict):
        return None
    return waiting_ahead(live_admission_view(envelope))


def follower_waiting_line(run: dict[str, Any], envelope: dict[str, Any]) -> str | None:
    """Return the follower waiting line for a queued run, if it changed."""

    view = live_admission_view(envelope)
    if not is_live_waiting(run, view if view is not None else stored_admission(run)):
        return None
    record = stored_admission(run)
    key = waiting_key(view if view is not None else record)
    limit = _as_int((view or {}).get("limit") if view else (record or {}).get("limit"))
    holders = _as_int((view or {}).get("holders") if view else None)
    ahead = waiting_ahead(view, record)
    if limit is None or holders is None or ahead is None:
        if ahead is None:
            return None
        return f"sase: waiting for a {key} slot ({ahead} ahead)"
    return (
        f"sase: waiting for a {key} slot "
        f"(limit {limit}: {holders} running, {ahead} ahead)"
    )


def follower_granted_line(run: dict[str, Any]) -> str | None:
    """Return the follower granted line once a queued run holds a slot."""

    record = stored_admission(run)
    if not isinstance(record, dict):
        return None
    if str(record.get("state") or "") != ADMITTED:
        return None
    key = waiting_key(record)
    return f"sase: {key} slot granted after {_format_wait_ms(record.get('wait_ms'))}"


__all__ = [
    "ABANDONED",
    "ADMITTED",
    "WAITING",
    "follower_granted_line",
    "follower_waiting_line",
    "is_live_waiting",
    "live_admission_view",
    "live_ahead",
    "show_admission_line",
    "stored_admission",
    "wait_json_admission",
    "waiting_ahead",
    "waiting_key",
    "waiting_marker",
    "waiting_timeout_line",
]
