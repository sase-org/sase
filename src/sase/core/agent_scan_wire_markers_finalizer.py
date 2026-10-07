"""Finalizer-status wire dataclasses for the agent scan facade.

Split out of :mod:`sase.core.agent_scan_wire_markers` to keep each module
under the 500-line cap. Covers the tolerant ``finalizer_status`` row
summary (plan §3.3 C5) carried by ``AgentMetaWire``. The per-file marker
projections that carry this summary live in
:mod:`sase.core.agent_scan_wire_markers`; import that module for the
stable import path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Maximum characters kept for any ``finalizer_status`` string (plan §3.3 C5).
FINALIZER_STATUS_STR_CAP = 120

#: Maximum per-run instance entries kept on the scan wire (plan §3.3 C5).
FINALIZER_STATUS_MAX_INSTANCES = 16


@dataclass(frozen=True)
class FinalizerStatusRunnerWire:
    """Runner that executed the finalizer phase (plan §3.3 C5)."""

    pid: int | None = None
    identity: str | None = None


@dataclass(frozen=True)
class FinalizerStatusInstanceWire:
    """One finalizer instance entry of the row summary (plan §3.3 C5)."""

    id: str = ""
    status: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    op: str | None = None
    step: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    headline: str | None = None
    warnings: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FinalizerStatusSummaryWire:
    """Tolerant row summary of finalizer execution (plan §3.3 C5)."""

    schema_version: int | None = None
    phase: str | None = None
    reason: str | None = None
    status: str | None = None
    plan_digest: str | None = None
    run_id: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    runner: FinalizerStatusRunnerWire | None = None
    instances: list[FinalizerStatusInstanceWire] = field(default_factory=list)
    instance_count: int | None = None


def _capped_status_str(value: object) -> str | None:
    """Return *value* capped to the C5 string ceiling, or None when not a str."""
    if not isinstance(value, str):
        return None
    if len(value) <= FINALIZER_STATUS_STR_CAP:
        return value
    return value[:FINALIZER_STATUS_STR_CAP]


def _status_int(value: object) -> int | None:
    """Return *value* as a non-negative int, or None when unusable.

    Bools, negative numbers, NaN/infinite floats, and non-numeric values are
    dropped, mirroring the Rust scanner's lenient coercion.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    return None


def _status_float(value: object) -> float | None:
    """Return *value* as a non-negative finite float, or None when unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number if number >= 0 else None
    return None


def finalizer_status_from_mapping(
    data: object,
) -> FinalizerStatusSummaryWire | None:
    """Coerce a raw ``finalizer_status`` mapping leniently (plan §3.3 C5).

    A non-mapping value, or a missing or empty ``phase`` string, gives None.
    Strings are capped at 120 characters, at most 16 instances are kept,
    entries without a string ``id`` are dropped, negative/NaN/non-numeric
    numbers are dropped, and unknown keys are ignored. A malformed summary
    never raises. Mirrors the Rust scanner's ``finalizer_status_from_value``.
    """
    if not isinstance(data, dict):
        return None
    phase = _capped_status_str(data.get("phase"))
    if not phase:
        return None
    raw_instances = data.get("instances")
    instances: list[FinalizerStatusInstanceWire] = []
    if isinstance(raw_instances, list):
        for entry in raw_instances:
            if not isinstance(entry, dict):
                continue
            entry_id = _capped_status_str(entry.get("id"))
            if not entry_id:
                continue
            instances.append(
                FinalizerStatusInstanceWire(
                    id=entry_id,
                    status=_capped_status_str(entry.get("status")),
                    attempt=_status_int(entry.get("attempt")),
                    max_attempts=_status_int(entry.get("max_attempts")),
                    op=_capped_status_str(entry.get("op")),
                    step=_capped_status_str(entry.get("step")),
                    started_at=_status_float(entry.get("started_at")),
                    finished_at=_status_float(entry.get("finished_at")),
                    headline=_capped_status_str(entry.get("headline")),
                    warnings=_status_int(entry.get("warnings")),
                    reason=_capped_status_str(entry.get("reason")),
                )
            )
            if len(instances) >= FINALIZER_STATUS_MAX_INSTANCES:
                break
    raw_runner = data.get("runner")
    runner: FinalizerStatusRunnerWire | None = None
    if isinstance(raw_runner, dict):
        runner = FinalizerStatusRunnerWire(
            pid=_status_int(raw_runner.get("pid")),
            identity=_capped_status_str(raw_runner.get("identity")),
        )
    return FinalizerStatusSummaryWire(
        schema_version=_status_int(data.get("schema_version")),
        phase=phase,
        reason=_capped_status_str(data.get("reason")),
        status=_capped_status_str(data.get("status")),
        plan_digest=_capped_status_str(data.get("plan_digest")),
        run_id=_capped_status_str(data.get("run_id")),
        started_at=_status_float(data.get("started_at")),
        updated_at=_status_float(data.get("updated_at")),
        runner=runner,
        instances=instances,
        instance_count=_status_int(data.get("instance_count")),
    )


__all__ = [
    "FINALIZER_STATUS_MAX_INSTANCES",
    "FINALIZER_STATUS_STR_CAP",
    "FinalizerStatusInstanceWire",
    "FinalizerStatusRunnerWire",
    "FinalizerStatusSummaryWire",
    "finalizer_status_from_mapping",
]
