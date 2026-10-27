"""Shared capacity view model for ``sase agent load`` and the TUI inspector.

This module is deliberately dependency-free (stdlib only, no Textual, no
Rich): it projects a :class:`MachineCapacityReport` plus an optional
``running_nodes`` count into typed, render-ready sections. The CLI renders
them with Rich; the capacity inspector modal renders the same sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from collections.abc import Mapping

_IDLE_GROUP_LIMIT = 10

_REASON_ORDER = (
    "not_started",
    "pending_question",
    "pending_gate",
    "explicit_zero_weight",
    "invalid_weight",
    "not_live",
    "no_pid",
    "done",
    "not_agent_record",
)

_REASON_LABELS = {
    "not_started": "not started",
    "pending_question": "waiting on a question",
    "pending_gate": "waiting on a gate",
    "explicit_zero_weight": "explicit zero weight",
    "invalid_weight": "invalid weight",
    "not_live": "not live",
    "no_pid": "no process evidence",
    "done": "done",
    "not_agent_record": "not an agent record",
}


@dataclass(frozen=True)
class CapacityHoldingRow:
    """One charged claim, shown once even when several records share it."""

    name: str
    kind: str
    charged_weight: float
    weight_source: str
    since: str | None
    authored_budget: int | None
    owner_key: str
    artifact_dir: str


@dataclass(frozen=True)
class CapacityRiderRow:
    """A live record riding a claim charged through another member."""

    name: str
    holder_name: str
    owner_key: str
    artifact_dir: str


@dataclass(frozen=True)
class CapacityIdleGroup:
    """Live records holding nothing, grouped by why they hold nothing."""

    reason_code: str
    reason_label: str
    count: int
    members: tuple[str, ...]
    truncated: bool
    hidden: int


@dataclass(frozen=True)
class CapacityQueuedRow:
    """One capacity waiter with the real blocker admission reports."""

    name: str
    queue_position: int
    requested_weight: float
    admission_limit: float
    blocker: str
    eligible: bool
    slot_requested_at: str | None


@dataclass(frozen=True)
class MachineCapacityView:
    """Render-ready projection of one :class:`MachineCapacityReport`."""

    headline: str
    limit_line: str
    snapshot_line: str
    running_line: str | None
    over_limit_note: str | None
    holdings: tuple[CapacityHoldingRow, ...]
    riders: tuple[CapacityRiderRow, ...]
    total_charged: float
    idle_groups: tuple[CapacityIdleGroup, ...]
    queued: tuple[CapacityQueuedRow, ...]
    diagnostics: tuple[str, ...]
    admission_blocked: bool
    accounting_unavailable: bool


def capacity_view(
    report: Any,
    *,
    running_nodes: int | None = None,
    now: float | None = None,
) -> MachineCapacityView:
    """Project *report* into typed display sections.

    *report* is a :class:`MachineCapacityReport` (duck-typed so tests can
    pass doubles). *running_nodes* is the TUI's live Running-bucket count;
    the CLI passes ``None`` and the running line is omitted. *now* defaults
    to the report's ``computed_at`` so snapshot ages stay deterministic.
    """
    moment = report.computed_at if now is None else now
    accounting = tuple(report.accounting)
    inputs = {
        record_inputs.artifact_dir: record_inputs
        for record_inputs in report.record_inputs
    }
    by_dir = {str(entry.get("artifact_dir")): entry for entry in accounting}
    names = {path: _display_name(entry) for path, entry in by_dir.items()}

    holdings: list[CapacityHoldingRow] = []
    for claim in report.claims:
        owner_key = str(claim.get("owner_key") or "")
        holder_dir = str(claim.get("owner_artifact_dir") or "")
        entry = by_dir.get(holder_dir)
        if entry is None:
            continue
        record = inputs.get(holder_dir)
        holdings.append(
            CapacityHoldingRow(
                name=names.get(holder_dir, holder_dir),
                kind=_holding_kind(entry, claim, record),
                charged_weight=float(entry.get("charged_weight") or 0.0),
                weight_source=str(entry.get("weight_source") or "unknown"),
                since=getattr(record, "run_started_at", None),
                authored_budget=getattr(record, "authored_queue_capacity", None),
                owner_key=owner_key,
                artifact_dir=holder_dir,
            )
        )
    holdings.sort(key=lambda row: row.name)

    riders: list[CapacityRiderRow] = []
    for entry in accounting:
        if str(entry.get("state")) != "riding_claim":
            continue
        path = str(entry.get("artifact_dir"))
        holder_dir = entry.get("claim_holder_artifact_dir")
        holder = str(holder_dir) if holder_dir else None
        riders.append(
            CapacityRiderRow(
                name=names.get(path, path),
                holder_name=names.get(holder, holder) if holder else "?",
                owner_key=str(entry.get("claim_owner_key") or ""),
                artifact_dir=path,
            )
        )
    riders.sort(key=lambda row: row.name)

    idle_groups = _idle_groups(accounting, names)
    queued = _queued_rows(report.waiters, names, inputs)

    occupied = float(report.occupied_capacity)
    limit = float(report.effective_limit)
    headroom = limit - occupied
    if report.over_limit:
        headline = (
            f"{_fmt(occupied)} of {_fmt(limit)} units in use · "
            f"{_fmt(-headroom)} over budget"
        )
    else:
        headline = (
            f"{_fmt(occupied)} of {_fmt(limit)} units in use · "
            f"{_fmt(headroom)} headroom"
        )

    limit_line = _limit_line(report.limit, limit, moment)
    diagnostics = tuple(_diagnostic_text(item) for item in report.diagnostics)
    snapshot_line = _snapshot_line(report, moment, len(diagnostics))
    running_line = _running_line(running_nodes, holdings)
    over_limit_note = (
        _over_limit_note(report, names, inputs) if report.over_limit else None
    )
    return MachineCapacityView(
        headline=headline,
        limit_line=limit_line,
        snapshot_line=snapshot_line,
        running_line=running_line,
        over_limit_note=over_limit_note,
        holdings=tuple(holdings),
        riders=tuple(riders),
        total_charged=_total(holdings),
        idle_groups=idle_groups,
        queued=queued,
        diagnostics=diagnostics,
        admission_blocked=not report.accounting_valid,
        accounting_unavailable=not report.accounting_available,
    )


def _display_name(entry: Mapping[str, Any]) -> str:
    name = entry.get("agent_name")
    if isinstance(name, str) and name:
        return name
    path = str(entry.get("artifact_dir") or "")
    return path.rsplit("/", 1)[-1] or path


def _holding_kind(
    entry: Mapping[str, Any], claim: Mapping[str, Any], record: Any
) -> str:
    if str(entry.get("weight_source")) == "explicit_zero":
        return "wait monitor"
    turn_kind = getattr(record, "turn_kind", None)
    if turn_kind == "monitor":
        return "verify monitor"
    if getattr(record, "turn_role", None) == "gate":
        return "gate"
    if str(claim.get("claim_kind")) == "parallel_member":
        return "parallel member"
    return "worker"


def _idle_groups(
    accounting: tuple[Mapping[str, Any], ...],
    names: dict[str, str],
) -> tuple[CapacityIdleGroup, ...]:
    by_reason: dict[str, list[str]] = {}
    for entry in accounting:
        if str(entry.get("state")) in ("holding", "riding_claim", "waiting"):
            continue
        reason = entry.get("reason_code")
        code = str(reason) if isinstance(reason, str) and reason else "not_started"
        path = str(entry.get("artifact_dir"))
        by_reason.setdefault(code, []).append(names.get(path, path))
    groups: list[CapacityIdleGroup] = []
    ordered = [code for code in _REASON_ORDER if code in by_reason]
    ordered.extend(sorted(code for code in by_reason if code not in _REASON_ORDER))
    for code in ordered:
        members = sorted(by_reason[code])
        shown = tuple(members[:_IDLE_GROUP_LIMIT])
        hidden = len(members) - len(shown)
        groups.append(
            CapacityIdleGroup(
                reason_code=code,
                reason_label=_REASON_LABELS.get(code, code.replace("_", " ")),
                count=len(members),
                members=shown,
                truncated=hidden > 0,
                hidden=hidden,
            )
        )
    return tuple(groups)


def _queued_rows(
    waiters: Any,
    names: dict[str, str],
    inputs: dict[str, Any],
) -> tuple[CapacityQueuedRow, ...]:
    rows: list[CapacityQueuedRow] = []
    for waiter in waiters:
        path = str(waiter.get("artifact_dir"))
        record = inputs.get(path)
        rows.append(
            CapacityQueuedRow(
                name=names.get(path, _fallback_name(path, record)),
                queue_position=int(waiter.get("queue_position") or 0),
                requested_weight=float(waiter.get("requested_weight") or 0.0),
                admission_limit=float(waiter.get("admission_limit") or 0.0),
                blocker=_blocker_text(waiter),
                eligible=bool(waiter.get("eligible")),
                slot_requested_at=waiter.get("slot_requested_at")
                or getattr(record, "slot_requested_at", None),
            )
        )
    return tuple(rows)


def _fallback_name(path: str, record: Any) -> str:
    monitor_id = getattr(record, "monitor_id", None)
    if isinstance(monitor_id, str) and monitor_id:
        return monitor_id
    return path.rsplit("/", 1)[-1] or path


def _blocker_text(waiter: Mapping[str, Any]) -> str:
    blockers = waiter.get("blockers")
    items = list(blockers) if isinstance(blockers, list) else []
    if not items:
        if waiter.get("eligible"):
            return "eligible · fits within budget"
        return "parked · waiting for capacity"
    return "; ".join(_one_blocker(item) for item in items if isinstance(item, Mapping))


def _one_blocker(blocker: Mapping[str, Any]) -> str:
    code = str(blocker.get("code") or "")
    if code == "insufficient-capacity":
        needed = _fmt(blocker.get("needed_capacity"))
        free = _fmt(blocker.get("free_capacity"))
        budget = _fmt(blocker.get("admission_limit"))
        return f"needs {needed} · {free} free · budget {budget} · blocked by capacity"
    if code == "hold-barrier":
        held_by = blocker.get("held_by") or "a hold"
        expires = blocker.get("hold_expires_at")
        if isinstance(expires, (int, float)):
            return f"held by {held_by} · until {_iso(expires)}"
        return f"held by {held_by}"
    if code == "weight-exceeds-limit":
        needed = _fmt(blocker.get("requested_weight", blocker.get("needed_capacity")))
        budget = _fmt(blocker.get("admission_limit"))
        return f"needs {needed} · over budget {budget} · never fits"
    if code == "deference-window":
        return "deferred · a better-priority waiter arrived first"
    message = blocker.get("message")
    if isinstance(message, str) and message:
        return message.rstrip(".")
    return code or "blocked"


def _limit_line(limit_snapshot: Any, effective: float, now: float) -> str:
    override = getattr(limit_snapshot, "temporary_override", None)
    configured = getattr(limit_snapshot, "configured_limit", None)
    expires_at = None if override is None else getattr(override, "expires_at", None)
    active = override is not None and (expires_at is None or float(expires_at) > now)
    if active and override is not None and configured is not None:
        source = _override_source(override)
        since = _iso(float(override.created_at))
        expires = getattr(override, "expires_at", None)
        expiry = "no expiry" if expires is None else f"until {_iso(float(expires))}"
        return (
            f"limit {_fmt(effective)}: {source} override since {since}, "
            f"{expiry} · config default {configured}"
        )
    if configured is not None:
        return f"limit {_fmt(effective)} · config default {configured}"
    return f"limit {_fmt(effective)}"


def _override_source(override: Any) -> str:
    source = str(getattr(override, "source", "") or "")
    if source.isalpha() and source.islower():
        return source.upper()
    return source or "override"


def _snapshot_line(report: Any, now: float, diagnostic_count: int) -> str:
    scanned = _timestamp(float(report.scanned_at))
    age = max(0.0, now - float(report.scanned_at))
    noun = "diagnostic" if diagnostic_count == 1 else "diagnostics"
    line = f"snapshot {scanned} · {age:.0f}s old · {diagnostic_count} {noun}"
    if not report.scan_current:
        line += " · stale (token changed)"
    return line


def _running_line(
    running_nodes: int | None, holdings: list[CapacityHoldingRow]
) -> str | None:
    if running_nodes is None:
        return None
    holding = sum(1 for row in holdings if row.charged_weight > 0)
    zero = sum(1 for row in holdings if row.charged_weight <= 0)
    return (
        f"{running_nodes} running nodes · {holding} holding capacity · {zero} holding 0"
    )


def _over_limit_note(report: Any, names: dict[str, str], inputs: dict[str, Any]) -> str:
    over = float(report.occupied_capacity) - float(report.effective_limit)
    budgeted = sorted(
        {
            f"{names.get(path, path)} (c{record.authored_queue_capacity})"
            for path, record in inputs.items()
            if getattr(record, "authored_queue_capacity", None) is not None
        }
    )
    note = f"over budget by {_fmt(over)}: no new work is admitted until load drops"
    if budgeted:
        note += f" · per-launch budgets in play: {', '.join(budgeted)}"
    else:
        note += " · admitted under per-launch %queue(capacity=N) budgets"
    return note


def _diagnostic_text(item: Any) -> str:
    if isinstance(item, Mapping):
        code = item.get("code")
        message = item.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return f"{code}: {message}"
        return str(dict(item))
    return str(item)


def _total(holdings: list[CapacityHoldingRow]) -> float:
    total = 0.0
    for row in holdings:
        total += row.charged_weight
    return total


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _iso(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "?"


def _timestamp(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return "?"


__all__ = [
    "CapacityHoldingRow",
    "CapacityIdleGroup",
    "CapacityQueuedRow",
    "CapacityRiderRow",
    "MachineCapacityView",
    "capacity_view",
]
