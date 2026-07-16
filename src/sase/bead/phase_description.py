"""Shared display text for deterministic epic phase beads."""

from __future__ import annotations


def generated_phase_description(plan_ref: str, phase_id: str) -> str:
    """Return the stable fallback pointer for a description-less phase."""
    return f"Phase `{phase_id}` in approved epic plan `{plan_ref}`."


__all__ = ["generated_phase_description"]
