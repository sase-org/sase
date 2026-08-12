"""Typed Python facade for chop-overrun classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sase.core.rust import require_rust_binding

from .state import ChopRunEntry

CHOP_OVERRUN_WIRE_SCHEMA_VERSION = 2

ChopOverrunLevel = Literal["none", "intermittent", "over"]


class ChopOverrunWireError(ValueError):
    """Raised when the Rust chop-overrun wire contract is incompatible."""


@dataclass(frozen=True)
class ChopOverrun:
    """How one chop's cached runs compare to its lumberjack interval."""

    level: ChopOverrunLevel
    sampled_runs: int
    over_runs: int
    worst_ratio: float | None
    worst_blocking_ms: int | None
    latest_ratio: float | None
    run_ratios: tuple[float | None, ...]


def classify_chop_overrun(
    *,
    now: datetime,
    interval_seconds: int,
    runs: Sequence[ChopRunEntry],
) -> ChopOverrun | None:
    """Classify cached chop runs through the required Rust binding.

    Returns ``None`` when there is intentionally no verdict to compute: the
    interval is unavailable/non-positive or there is no cached run history.
    All binding and schema problems are raised for the caller to handle.
    """
    if (
        not isinstance(interval_seconds, int)
        or isinstance(interval_seconds, bool)
        or interval_seconds <= 0
        or not runs
    ):
        return None

    version_binding = require_rust_binding("chop_overrun_wire_schema_version")
    binding_version = version_binding()
    if (
        not isinstance(binding_version, int)
        or isinstance(binding_version, bool)
        or binding_version != CHOP_OVERRUN_WIRE_SCHEMA_VERSION
    ):
        raise ChopOverrunWireError(
            "chop-overrun binding schema mismatch: "
            f"got {binding_version!r}, expected {CHOP_OVERRUN_WIRE_SCHEMA_VERSION}"
        )

    classifier = require_rust_binding("classify_chop_overrun")
    payload = classifier(
        {
            "schema_version": CHOP_OVERRUN_WIRE_SCHEMA_VERSION,
            "now": now.isoformat(),
            "interval_seconds": interval_seconds,
            "runs": [_run_to_wire(run) for run in runs],
        }
    )
    return _rehydrate_chop_overrun(payload, expected_run_count=len(runs))


def _run_to_wire(run: ChopRunEntry) -> dict[str, Any]:
    return {
        "status": run.status,
        "started_at": run.started_at,
        "duration_ms": run.duration_ms,
        "script_duration_ms": run.script_duration_ms,
    }


def _rehydrate_chop_overrun(
    payload: Any,
    *,
    expected_run_count: int,
) -> ChopOverrun:
    if not isinstance(payload, dict):
        raise ChopOverrunWireError("chop-overrun binding returned a non-mapping result")

    version = payload.get("schema_version")
    if version != CHOP_OVERRUN_WIRE_SCHEMA_VERSION:
        raise ChopOverrunWireError(
            "chop-overrun response schema mismatch: "
            f"got {version!r}, expected {CHOP_OVERRUN_WIRE_SCHEMA_VERSION}"
        )

    missing = {
        key
        for key in (
            "level",
            "sampled_runs",
            "over_runs",
            "worst_ratio",
            "worst_blocking_ms",
            "latest_ratio",
            "run_ratios",
        )
        if key not in payload
    }
    if missing:
        raise ChopOverrunWireError(
            "chop-overrun binding response missing fields: "
            + ", ".join(sorted(missing))
        )

    level = payload["level"]
    if level not in {"none", "intermittent", "over"}:
        raise ChopOverrunWireError(
            f"chop-overrun binding returned unsupported level {level!r}"
        )
    sampled_runs = _expect_non_bool_int(payload["sampled_runs"], "sampled_runs")
    over_runs = _expect_non_bool_int(payload["over_runs"], "over_runs")
    worst_blocking_ms = _optional_non_bool_int(
        payload["worst_blocking_ms"], "worst_blocking_ms"
    )
    worst_ratio = _optional_number(payload["worst_ratio"], "worst_ratio")
    latest_ratio = _optional_number(payload["latest_ratio"], "latest_ratio")
    run_ratios = _run_ratios(
        payload["run_ratios"],
        expected_run_count=expected_run_count,
    )

    return ChopOverrun(
        level=level,
        sampled_runs=sampled_runs,
        over_runs=over_runs,
        worst_ratio=worst_ratio,
        worst_blocking_ms=worst_blocking_ms,
        latest_ratio=latest_ratio,
        run_ratios=run_ratios,
    )


def _expect_non_bool_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ChopOverrunWireError(
            f"chop-overrun binding returned invalid {field}: {value!r}"
        )
    return value


def _optional_non_bool_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _expect_non_bool_int(value, field)


def _optional_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ChopOverrunWireError(
            f"chop-overrun binding returned invalid {field}: {value!r}"
        )
    return float(value)


def _run_ratios(value: Any, *, expected_run_count: int) -> tuple[float | None, ...]:
    if not isinstance(value, list):
        raise ChopOverrunWireError(
            f"chop-overrun binding returned invalid run_ratios: {value!r}"
        )
    if len(value) != expected_run_count:
        raise ChopOverrunWireError(
            "chop-overrun binding returned run_ratios length "
            f"{len(value)}, expected {expected_run_count}"
        )
    return tuple(
        _optional_number(item, f"run_ratios[{idx}]") for idx, item in enumerate(value)
    )


__all__ = [
    "CHOP_OVERRUN_WIRE_SCHEMA_VERSION",
    "ChopOverrun",
    "ChopOverrunLevel",
    "ChopOverrunWireError",
    "classify_chop_overrun",
]
