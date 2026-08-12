"""Accessible Rich presentation helpers for normalized plan-file tiers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.sdd.plan_tiers import normalize_plan_tier

PlanTierValue = Literal["tale", "epic"]


@dataclass(frozen=True)
class _PlanTierPresentation:
    """Cross-surface label and accent metadata for one plan tier."""

    label: str
    accent_color: str

    @property
    def rich_style(self) -> str:
        """Return the standard bold Rich style used for the tier word."""
        return f"bold {self.accent_color}"


PLAN_TIER_PRESENTATIONS: dict[PlanTierValue, _PlanTierPresentation] = {
    "tale": _PlanTierPresentation(label="Tale", accent_color="#FFD75F"),
    "epic": _PlanTierPresentation(label="Epic", accent_color="#AF87FF"),
}

# Fallback for a notification whose tier could not be resolved from any layer.
GENERIC_PLAN_LABEL = "Plan"
GENERIC_PLAN_ACCENT = "#5FD7FF"


def normalize_plan_tier_value(value: object) -> PlanTierValue | None:
    """Return an exact normalized plan tier without guessing invalid values."""
    normalized = normalize_plan_tier(value)
    if normalized not in PLAN_TIER_PRESENTATIONS:
        return None
    return normalized  # type: ignore[return-value]


def plan_tier_presentation(value: object) -> _PlanTierPresentation:
    """Return presentation metadata for a valid plan tier."""
    normalized = normalize_plan_tier_value(value)
    if normalized is None:
        raise ValueError(f"unknown plan tier: {value!r}")
    return PLAN_TIER_PRESENTATIONS[normalized]


__all__ = [
    "GENERIC_PLAN_ACCENT",
    "GENERIC_PLAN_LABEL",
    "PLAN_TIER_PRESENTATIONS",
    "PlanTierValue",
    "normalize_plan_tier_value",
    "plan_tier_presentation",
]
