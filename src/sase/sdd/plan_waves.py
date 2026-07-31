"""Shared dependency-wave layering for authored epic plan phases."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _WavePhase(Protocol):
    """Structural shape shared by ``PlanDisplayPhase`` and ``ValidatedPlanPhase``.

    Declared as read-only properties, not plain attribute annotations: a
    frozen dataclass field does not satisfy a Protocol member that mypy
    treats as requiring a mutable attribute.
    """

    @property
    def id(self) -> str: ...

    @property
    def depends_on(self) -> tuple[str, ...]: ...


def plan_phase_waves(
    phases: Iterable[_WavePhase],
) -> tuple[tuple[str, ...], ...] | None:
    """Layer *phases* into Kahn-style dependency waves.

    Wave *k* holds every phase whose dependencies all land in an earlier
    wave. Authored order is preserved both across and within waves. Returns
    ``None`` when a dependency cycle, or a dependency on an id outside
    *phases*, leaves some phase unable to ever join a wave.
    """
    phase_map = {phase.id: phase for phase in phases}
    remaining = {
        phase_id: set(phase.depends_on) for phase_id, phase in phase_map.items()
    }
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while remaining:
        wave = tuple(
            phase_id
            for phase_id in phase_map
            if phase_id in remaining and remaining[phase_id] <= completed
        )
        if not wave:
            return None
        waves.append(wave)
        completed.update(wave)
        for phase_id in wave:
            del remaining[phase_id]
    return tuple(waves)


__all__ = ["plan_phase_waves"]
