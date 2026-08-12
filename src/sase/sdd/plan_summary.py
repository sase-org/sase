"""Phase/wave/size counts derived from a validated plan, and their wire codec.

``plan_counts_summary`` folds a ``PlanValidationResult`` into a compact
``_PlanCountsSummary``. ``encode_plan_counts``/``decode_plan_counts`` are the
two halves of a small string-keyed codec used to carry that summary through
``Notification.action_data`` — a compatibility surface written by the process
that creates a plan gate and read by a different process (the ACE TUI) later,
so the key names and formats below are a contract, not an implementation
detail:

- ``plan_tier``: ``"tale"`` or ``"epic"``, always present.
- ``plan_phase_count``: decimal phase count, epic tier only.
- ``plan_wave_count``: decimal wave count, epic tier only, omitted when wave
  layering is unavailable (a dependency cycle or dangling reference).
- ``plan_phase_sizes``: comma-joined ``size=count`` pairs in canonical
  ``PHASE_SIZE_VALUES`` order (e.g. ``"xsmall=1,small=2,medium=3"``), epic
  tier only, omitted entirely when there are no sized phases.

``decode_plan_counts`` is total: malformed input degrades field-by-field
instead of raising, since it runs on the render path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.phase_size_presentation import (
    PHASE_SIZE_VALUES,
    PhaseSizeValue,
    normalize_phase_size,
)
from sase.plan_tier_presentation import PlanTierValue, normalize_plan_tier_value
from sase.sdd.plan_validate import PlanValidationResult
from sase.sdd.plan_waves import plan_phase_waves


@dataclass(frozen=True, slots=True)
class _PlanCountsSummary:
    """Phase/wave/size shape of one validated plan revision."""

    tier: PlanTierValue
    phase_count: int
    wave_count: int | None
    size_counts: tuple[tuple[PhaseSizeValue, int], ...]


def plan_counts_summary(
    validation: PlanValidationResult, *, tier: PlanTierValue
) -> _PlanCountsSummary | None:
    """Derive phase/wave/size counts from a validated plan.

    Returns ``None`` when ``validation.plan`` is unavailable (validation
    failed), since there is nothing to summarize.
    """
    if validation.plan is None:
        return None

    phases = validation.plan.phases
    waves = plan_phase_waves(phases)
    wave_count = len(waves) if waves is not None else None

    histogram: dict[PhaseSizeValue, int] = {}
    for phase in phases:
        size = normalize_phase_size(phase.size)
        if size is None:
            continue
        histogram[size] = histogram.get(size, 0) + 1
    size_counts: tuple[tuple[PhaseSizeValue, int], ...] = tuple(
        (size, histogram[size]) for size in PHASE_SIZE_VALUES if histogram.get(size)
    )

    return _PlanCountsSummary(
        tier=tier,
        phase_count=len(phases),
        wave_count=wave_count,
        size_counts=size_counts,
    )


def encode_plan_counts(summary: _PlanCountsSummary) -> dict[str, str]:
    """Encode *summary* into the ``action_data`` string codec."""
    encoded: dict[str, str] = {"plan_tier": summary.tier}
    if summary.tier != "epic":
        return encoded

    encoded["plan_phase_count"] = str(summary.phase_count)
    if summary.wave_count is not None:
        encoded["plan_wave_count"] = str(summary.wave_count)
    if summary.size_counts:
        encoded["plan_phase_sizes"] = ",".join(
            f"{size}={count}" for size, count in summary.size_counts
        )
    return encoded


def decode_plan_counts(action_data: Mapping[str, str]) -> _PlanCountsSummary | None:
    """Decode a ``_PlanCountsSummary`` from ``action_data``. Never raises.

    Returns ``None`` when the tier is missing or unrecognized. Otherwise every
    other field degrades independently on malformed input: a missing or
    invalid ``plan_phase_count`` becomes ``0``, an invalid ``plan_wave_count``
    becomes ``None``, and unparsable entries in ``plan_phase_sizes`` are
    skipped rather than failing the whole field.
    """
    tier = normalize_plan_tier_value(action_data.get("plan_tier"))
    if tier is None:
        return None
    if tier != "epic":
        return _PlanCountsSummary(
            tier=tier, phase_count=0, wave_count=None, size_counts=()
        )

    phase_count = _parse_non_negative_int(action_data.get("plan_phase_count")) or 0
    wave_count = _parse_non_negative_int(action_data.get("plan_wave_count"))
    size_counts = _parse_size_counts(action_data.get("plan_phase_sizes"))
    return _PlanCountsSummary(
        tier=tier,
        phase_count=phase_count,
        wave_count=wave_count,
        size_counts=size_counts,
    )


def _parse_non_negative_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _parse_size_counts(value: str | None) -> tuple[tuple[PhaseSizeValue, int], ...]:
    if not value:
        return ()
    histogram: dict[PhaseSizeValue, int] = {}
    for entry in value.split(","):
        name, _, raw_count = entry.partition("=")
        size = normalize_phase_size(name)
        if size is None:
            continue
        count = _parse_non_negative_int(raw_count)
        if count is None:
            continue
        histogram[size] = count
    return tuple(
        (size, histogram[size]) for size in PHASE_SIZE_VALUES if size in histogram
    )


__all__ = [
    "decode_plan_counts",
    "encode_plan_counts",
    "plan_counts_summary",
]
