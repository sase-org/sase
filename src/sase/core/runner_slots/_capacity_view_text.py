"""Headlines, verdicts, limit copy, and blocker sentences for the capacity view."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ._capacity_view import (
    CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS,
    CapacityHoldingRow,
    CapacityIdleGroup,
    CapacityLimitInfo,
    CapacityQueuedRow,
    CapacityRiderRow,
    CapacityVerdict,
    MachineCapacityView,
)


def assemble_capacity_view(
    report: Any,
    *,
    moment: float,
    running_nodes: int | None,
    holdings: list[CapacityHoldingRow],
    riders: list[CapacityRiderRow],
    charged: tuple[CapacityHoldingRow, ...],
    zero_weight: tuple[CapacityHoldingRow, ...],
    idle_groups: tuple[CapacityIdleGroup, ...],
    attention_groups: tuple[CapacityIdleGroup, ...],
    waiting_groups: tuple[CapacityIdleGroup, ...],
    inactive_groups: tuple[CapacityIdleGroup, ...],
    queued: tuple[CapacityQueuedRow, ...],
    names: dict[str, str],
    inputs: dict[str, Any],
) -> MachineCapacityView:
    """Attach headlines, verdict, and limit copy to already-built rows."""
    occupied = float(report.occupied_capacity)
    limit = float(report.effective_limit)
    headroom = limit - occupied
    if report.over_limit:
        headline = (
            f"{_fmt(occupied)} of "
            f"{_fmt(limit)} units in use · "
            f"{_fmt(-headroom)} over budget"
        )
    else:
        headline = (
            f"{_fmt(occupied)} of "
            f"{_fmt(limit)} units in use · "
            f"{_fmt(headroom)} headroom"
        )
    diagnostics = tuple(_diagnostic_text(item) for item in report.diagnostics)
    over_limit_note = (
        _over_limit_note(report, names, inputs) if report.over_limit else None
    )
    return MachineCapacityView(
        headline=headline,
        limit_line=_limit_line(report.limit, limit, moment),
        snapshot_line=_snapshot_line(report, moment, len(diagnostics)),
        running_line=_running_line(running_nodes, holdings),
        over_limit_note=over_limit_note,
        holdings=tuple(holdings),
        riders=tuple(riders),
        total_charged=sum(row.charged_weight for row in holdings),
        idle_groups=idle_groups,
        queued=queued,
        diagnostics=diagnostics,
        admission_blocked=not report.accounting_valid,
        accounting_unavailable=not report.accounting_available,
        occupied=occupied,
        limit=limit,
        free=headroom,
        verdict=_verdict(
            report,
            occupied,
            limit,
            headroom,
            queued,
            names=names,
            inputs=inputs,
        ),
        limit_info=_limit_info(report.limit, limit, moment),
        computed_at=float(report.computed_at),
        scan_age_seconds=max(0.0, moment - float(report.scanned_at)),
        scan_current=bool(report.scan_current),
        charged=charged,
        zero_weight=zero_weight,
        attention_groups=attention_groups,
        waiting_groups=waiting_groups,
        inactive_groups=inactive_groups,
    )


def _fmt(value: Any) -> str:
    """Format a capacity quantity, preferring integers."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def seconds_since_stamp(moment: float, stamp: object) -> float | None:
    """Return seconds from an ISO timestamp to *moment*, or ``None``."""
    if not isinstance(stamp, str) or not stamp:
        return None
    text = stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return moment - parsed.timestamp()


def capacity_blocker_text(waiter: Mapping[str, Any]) -> str:
    """Join every blocker on *waiter* into one display sentence."""
    blockers = waiter.get("blockers")
    items = list(blockers) if isinstance(blockers, list) else []
    if not items:
        if waiter.get("eligible"):
            return "eligible · fits within budget"
        return "parked · waiting for capacity"
    return "; ".join(
        capacity_one_blocker(item) for item in items if isinstance(item, Mapping)
    )


def capacity_one_blocker(blocker: Mapping[str, Any]) -> str:
    """Render one admission blocker mapping as display text."""
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
    """Return the legacy one-line limit provenance string."""
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
            f"limit {_fmt(effective)}: {source} override "
            f"since {since}, {expiry} · config default {configured}"
        )
    if configured is not None:
        return f"limit {_fmt(effective)} · config default {configured}"
    return f"limit {_fmt(effective)}"


def _limit_info(limit_snapshot: Any, effective: float, now: float) -> CapacityLimitInfo:
    """Return structured limit provenance for the inspector facts row."""
    override = getattr(limit_snapshot, "temporary_override", None)
    configured = getattr(limit_snapshot, "configured_limit", None)
    expires_at = None if override is None else getattr(override, "expires_at", None)
    active = override is not None and (expires_at is None or float(expires_at) > now)
    if not active or override is None:
        return CapacityLimitInfo(
            effective=effective,
            configured=None if configured is None else float(configured),
            override_source=None,
            override_created_at=None,
            override_expires_at=None,
            override_age_seconds=None,
            override_long_lived=False,
        )
    created_at = float(override.created_at)
    age = now - created_at
    expires = getattr(override, "expires_at", None)
    return CapacityLimitInfo(
        effective=effective,
        configured=None if configured is None else float(configured),
        override_source=_override_source(override),
        override_created_at=created_at,
        override_expires_at=None if expires is None else float(expires),
        override_age_seconds=age,
        override_long_lived=age >= CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS,
    )


def _snapshot_line(report: Any, now: float, diagnostic_count: int) -> str:
    """Return the legacy snapshot-age line."""
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
    """Return the running-nodes summary, or ``None`` when the TUI omits it."""
    if running_nodes is None:
        return None
    holding = sum(1 for row in holdings if row.charged_weight > 0)
    zero = sum(1 for row in holdings if row.charged_weight <= 0)
    return (
        f"{running_nodes} running nodes · {holding} holding capacity · {zero} holding 0"
    )


def _over_limit_note(report: Any, names: dict[str, str], inputs: dict[str, Any]) -> str:
    """Return the legacy over-budget note, including the per-launch clause."""
    over = float(report.occupied_capacity) - float(report.effective_limit)
    note = f"over budget by {_fmt(over)}: no new work is admitted until load drops"
    return f"{note} · {_over_limit_budget_clause(names, inputs)}"


def _verdict(
    report: Any,
    occupied: float,
    limit: float,
    free: float,
    queued: tuple[CapacityQueuedRow, ...],
    *,
    names: dict[str, str],
    inputs: dict[str, Any],
) -> CapacityVerdict:
    """Return the first matching verdict for *report*."""
    if not report.accounting_available:
        return CapacityVerdict(
            tone="unknown",
            title="Holder accounting unavailable — totals only",
            detail="This sase-core build cannot explain individual holders.",
        )
    if not report.accounting_valid:
        return CapacityVerdict(
            tone="blocked",
            title="Admission blocked — capacity accounting is invalid",
            detail=(
                f"{_fmt(occupied)} is a known subtotal, "
                "not free capacity · see Needs attention"
            ),
        )
    if report.over_limit:
        over = occupied - limit
        return CapacityVerdict(
            tone="over",
            title=(
                f"Over budget by {_fmt(over)} — no new work starts until load drops"
            ),
            detail=_over_limit_budget_clause(names, inputs),
        )
    queue_summary = _queue_summary(queued)
    if free <= 1e-9:
        return CapacityVerdict(
            tone="full",
            title=f"Full — all {_count_noun(limit, 'unit')} in use",
            detail=(
                queue_summary
                if queue_summary is not None
                else "The next launch will queue until a unit frees up."
            ),
        )
    if free < 1:
        return CapacityVerdict(
            tone="tight",
            title=(f"{_fmt(free)} unit free — a default-weight agent would queue"),
            detail=queue_summary,
        )
    room = math.floor(free)
    agent_noun = "default-weight agent" if room == 1 else "default-weight agents"
    if queued:
        head = _queue_head(queued)
        detail = (
            f"{_fmt(len(queued))} still queued · "
            f"#{head.queue_position} {head.name}: {head.blocker}"
        )
    else:
        detail = None
    return CapacityVerdict(
        tone="ok",
        title=(
            f"{_count_noun(free, 'unit')} free — room for "
            f"{_fmt(float(room))} more {agent_noun}"
        ),
        detail=detail,
    )


def _diagnostic_text(item: Any) -> str:
    """Render one report diagnostic as a single line."""
    if isinstance(item, Mapping):
        code = item.get("code")
        message = item.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return f"{code}: {message}"
        return str(dict(item))
    return str(item)


def _over_limit_budget_clause(names: dict[str, str], inputs: dict[str, Any]) -> str:
    budgeted = sorted(
        {
            f"{names.get(path, path)} (c{record.authored_queue_capacity})"
            for path, record in inputs.items()
            if getattr(record, "authored_queue_capacity", None) is not None
        }
    )
    if budgeted:
        return f"per-launch budgets in play: {', '.join(budgeted)}"
    return "admitted under per-launch %queue(capacity=N) budgets"


def _queue_head(queued: tuple[CapacityQueuedRow, ...]) -> CapacityQueuedRow:
    return min(queued, key=lambda row: (row.queue_position, row.name))


def _queue_summary(queued: tuple[CapacityQueuedRow, ...]) -> str | None:
    if not queued:
        return None
    head = _queue_head(queued)
    return (
        f"{_fmt(len(queued))} queued · next up "
        f"#{head.queue_position} {head.name}: {head.blocker}"
    )


def _count_noun(value: float, singular: str) -> str:
    noun = singular if abs(value - 1.0) < 1e-9 else f"{singular}s"
    return f"{_fmt(value)} {noun}"


def _override_source(override: Any) -> str:
    source = str(getattr(override, "source", "") or "")
    if source.isalpha() and source.islower():
        return source.upper()
    return source or "override"


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
