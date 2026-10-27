"""Read-only authoritative machine capacity report.

CLI, ``sase agent list``, and the TUI all consume :class:`MachineCapacityReport`.
Computation reuses admission's scan cache, a fresh liveness probe, a
non-mutating hold peek, and the same Rust snapshot call admission uses,
minus the candidate and ``runner_slots.lock``.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.local_machine import local_machine_label

from ._admission_types import RecordLiveness
from ._scan import collect_runner_slot_records, record_liveness_probe
from ._scan_cache import (
    RunnerSlotScanCache,
    load_or_refresh_runner_slot_scan,
    read_runner_slot_scan_cache,
)
from ._signal import runner_slot_state_token

DISPLAY_RESCAN_INTERVAL_SECONDS = 30.0
_OVER_LIMIT_ABS_TOL = 1e-9

_display_rescan_lock = threading.Lock()
_last_display_rescan_at: float | None = None


@dataclass(frozen=True)
class MachineCapacityRecordInputs:
    """Per-record presentation fields the Rust snapshot does not echo."""

    artifact_dir: str
    turn_kind: str | None
    turn_role: str | None
    monitor_id: str | None
    slot_requested_at: str | None
    authored_queue_capacity: int | None
    run_started_at: str | None


@dataclass(frozen=True)
class MachineCapacityReport:
    """The only capacity input CLI, list, and TUI displays should read."""

    machine: str
    computed_at: float
    scanned_at: float
    token: str
    scan_current: bool
    effective_limit: float
    limit: EffectiveRunnerLimitSnapshot
    occupied_capacity: float
    occupied_lanes: int
    over_limit: bool
    claims: tuple[dict[str, Any], ...]
    waiters: tuple[dict[str, Any], ...]
    accounting: tuple[dict[str, Any], ...]
    diagnostics: tuple[Any, ...]
    accounting_valid: bool
    accounting_available: bool
    raw_snapshot: dict[str, Any]
    record_inputs: tuple[MachineCapacityRecordInputs, ...]


def machine_capacity_report(
    *,
    now: float | None = None,
    force_rescan: bool = False,
    is_live: RecordLiveness | None = None,
    collect: Callable[[], list[AgentArtifactRecordWire]] | None = None,
) -> MachineCapacityReport:
    """Build this machine's capacity report without taking the admission lock.

    Display-initiated cache rescans are rate-limited to one per 30 s with at
    most one in flight. Matching the live token reuses the cached records at
    any age. *force_rescan* is the CLI ``-r`` path.
    """
    timestamp = time.time() if now is None else now
    records, scanned_at, scan_token, scan_current = _display_scan_records(
        now=timestamp,
        force_rescan=force_rescan,
        collect=collect_runner_slot_records if collect is None else collect,
    )
    from sase.config.core import get_configured_max_running_agents
    from sase.config.runner_limit_override import get_active_runner_limit_override
    from sase.core.agent_hold_facade import peek_active_agent_holds

    override = get_active_runner_limit_override(timestamp)
    limit = EffectiveRunnerLimitSnapshot(
        configured_limit=get_configured_max_running_agents(),
        temporary_override=override,
        captured_at=timestamp,
    )
    return machine_capacity_report_from_records(
        records,
        record_liveness_probe() if is_live is None else is_live,
        now=timestamp,
        token=scan_token,
        scanned_at=scanned_at,
        scan_current=scan_current,
        limit=limit,
        active_holds=peek_active_agent_holds(now=timestamp),
    )


def machine_capacity_report_from_records(
    records: Sequence[AgentArtifactRecordWire],
    is_live: RecordLiveness,
    *,
    now: float,
    token: str,
    scanned_at: float,
    scan_current: bool,
    limit: EffectiveRunnerLimitSnapshot,
    active_holds: Iterable[Mapping[str, Any]] = (),
) -> MachineCapacityReport:
    """Project already-loaded scan records into a machine capacity report."""
    from sase.config.core import (
        get_runner_slot_deference_max_seconds,
        get_runner_slot_deference_seconds_per_step,
    )

    from ._admission_snapshot import runner_capacity_snapshot

    effective_limit = float(limit.effective_limit(now))
    snapshot = runner_capacity_snapshot(
        records,
        is_live,
        effective_limit=effective_limit,
        now=datetime.fromtimestamp(now, tz=UTC).isoformat(),
        deference_seconds_per_step=get_runner_slot_deference_seconds_per_step(),
        deference_max_seconds=get_runner_slot_deference_max_seconds(),
        candidate=None,
        active_holds=active_holds,
    )
    return _report_from_snapshot(
        snapshot,
        records=records,
        now=now,
        token=token,
        scanned_at=scanned_at,
        scan_current=scan_current,
        limit=limit,
        effective_limit=effective_limit,
    )


def _display_scan_records(
    *,
    now: float,
    force_rescan: bool,
    collect: Callable[[], list[AgentArtifactRecordWire]],
) -> tuple[list[AgentArtifactRecordWire], float, str, bool]:
    live_token = runner_slot_state_token()
    cached = read_runner_slot_scan_cache()
    if not force_rescan and cached is not None and cached.token == live_token:
        return list(cached.records), cached.scanned_at, cached.token, True

    if not force_rescan and cached is not None:
        acquired = _display_rescan_lock.acquire(blocking=False)
        if not acquired:
            return _stale_scan(cached)
        try:
            if _display_rescan_rate_limited(now):
                return _stale_scan(cached)
            return _run_display_rescan(collect, live_token=live_token, now=now)
        finally:
            _display_rescan_lock.release()

    with _display_rescan_lock:
        return _run_display_rescan(collect, live_token=live_token, now=now)


def _display_rescan_rate_limited(now: float) -> bool:
    return (
        _last_display_rescan_at is not None
        and now - _last_display_rescan_at < DISPLAY_RESCAN_INTERVAL_SECONDS
    )


def _stale_scan(
    cached: RunnerSlotScanCache,
) -> tuple[list[AgentArtifactRecordWire], float, str, bool]:
    return list(cached.records), cached.scanned_at, cached.token, False


def _run_display_rescan(
    collect: Callable[[], list[AgentArtifactRecordWire]],
    *,
    live_token: str,
    now: float,
) -> tuple[list[AgentArtifactRecordWire], float, str, bool]:
    global _last_display_rescan_at
    records = load_or_refresh_runner_slot_scan(
        collect,
        max_age=0.0,
        now=now,
        token=live_token,
    )
    _last_display_rescan_at = now
    return records, now, live_token, True


def _report_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    records: Sequence[AgentArtifactRecordWire],
    now: float,
    token: str,
    scanned_at: float,
    scan_current: bool,
    limit: EffectiveRunnerLimitSnapshot,
    effective_limit: float,
) -> MachineCapacityReport:
    raw = dict(snapshot)
    accounting_raw = raw.get("accounting")
    accounting_available = isinstance(accounting_raw, list)
    accounting = _maps(accounting_raw) if accounting_available else ()
    occupied = _finite_float(raw.get("occupied_capacity")) or 0.0
    snapshot_limit = _finite_float(raw.get("effective_limit"))
    report_limit = effective_limit if snapshot_limit is None else snapshot_limit
    lanes = raw.get("occupied_lanes")
    return MachineCapacityReport(
        machine=local_machine_label(),
        computed_at=now,
        scanned_at=scanned_at,
        token=token,
        scan_current=scan_current,
        effective_limit=report_limit,
        limit=limit,
        occupied_capacity=occupied,
        occupied_lanes=lanes if type(lanes) is int else 0,
        over_limit=_over_limit(occupied, report_limit),
        claims=_maps(raw.get("claims")),
        waiters=_maps(raw.get("waiters")),
        accounting=accounting,
        diagnostics=_items(raw.get("diagnostics")),
        accounting_valid=accounting_available and raw.get("accounting_valid") is True,
        accounting_available=accounting_available,
        raw_snapshot=raw,
        record_inputs=tuple(_record_inputs(record) for record in records),
    )


def _record_inputs(record: AgentArtifactRecordWire) -> MachineCapacityRecordInputs:
    meta = record.agent_meta
    waiting = record.waiting
    turn = None if meta is None else meta.agent_session_turn
    monitor_id = None
    if turn is not None and turn.kind == "monitor":
        monitor_id = turn.id
    return MachineCapacityRecordInputs(
        artifact_dir=record.artifact_dir,
        turn_kind=None if turn is None else turn.kind,
        turn_role=None if meta is None else meta.agent_session_role,
        monitor_id=monitor_id,
        slot_requested_at=None if waiting is None else waiting.slot_requested_at,
        authored_queue_capacity=_authored_queue_capacity(record),
        run_started_at=None if meta is None else meta.run_started_at,
    )


def _authored_queue_capacity(record: AgentArtifactRecordWire) -> int | None:
    waiting = record.waiting
    if (
        waiting is not None
        and type(waiting.queue_capacity) is int
        and waiting.queue_capacity >= 0
    ):
        return waiting.queue_capacity
    if (
        waiting is not None
        and type(waiting.wait_runners) is int
        and waiting.wait_runners >= 0
    ):
        return waiting.wait_runners
    meta = record.agent_meta
    if (
        meta is not None
        and type(meta.queue_capacity) is int
        and meta.queue_capacity >= 0
    ):
        return meta.queue_capacity
    if meta is not None and type(meta.wait_runners) is int and meta.wait_runners >= 0:
        return meta.wait_runners
    return None


def _over_limit(occupied: float, limit: float) -> bool:
    return occupied > limit and not math.isclose(
        occupied, limit, rel_tol=0.0, abs_tol=_OVER_LIMIT_ABS_TOL
    )


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _maps(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _items(value: object) -> tuple[Any, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(value)


__all__ = [
    "DISPLAY_RESCAN_INTERVAL_SECONDS",
    "MachineCapacityRecordInputs",
    "MachineCapacityReport",
    "machine_capacity_report",
    "machine_capacity_report_from_records",
]
