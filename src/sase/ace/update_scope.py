"""Scope vocabulary for snapshot-gated comprehensive updates."""

from __future__ import annotations

from enum import StrEnum


class UpdateLeg(StrEnum):
    """One independently planned comprehensive-update leg."""

    SASE = "sase"
    PROVIDERS = "providers"
    AGENTS = "agents"


ALL_LEGS: frozenset[UpdateLeg] = frozenset(
    (UpdateLeg.SASE, UpdateLeg.PROVIDERS, UpdateLeg.AGENTS)
)


class UpdateScope(StrEnum):
    """User-facing update selection and the legs it includes."""

    EVERYTHING = "everything"
    SASE = "sase"
    PROVIDERS = "providers"
    AGENTS = "agents"

    @property
    def legs(self) -> frozenset[UpdateLeg]:
        """Return the legs this scope selects."""
        if self is UpdateScope.EVERYTHING:
            return ALL_LEGS
        return frozenset({UpdateLeg(self.value)})


__all__ = ["ALL_LEGS", "UpdateLeg", "UpdateScope"]
