"""Facade for the shared Rust editor fuzzy matcher."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from sase.core.rust import require_rust_binding


@dataclass(frozen=True, slots=True)
class FuzzyMatch:
    """Shared fuzzy match result using character-indexed match runs."""

    tier: int
    score: int
    runs: tuple[tuple[int, int], ...]


def fuzzy_match(query: str, text: str) -> FuzzyMatch | None:
    """Fuzzy-match *query* against *text* through ``sase_core_rs``."""
    binding = require_rust_binding("fuzzy_match")
    raw = binding(query, text)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise RuntimeError("sase_core_rs fuzzy_match returned a non-mapping result")
    return FuzzyMatch(
        tier=int(raw["tier"]),
        score=int(raw["score"]),
        runs=_runs_from_wire(raw.get("runs")),
    )


def fuzzy_sort_key(match: FuzzyMatch, text: str) -> tuple[int, int, int, str, str]:
    """Return the Python equivalent of Rust ``compare_fuzzy`` ordering."""
    return (match.tier, -match.score, len(text), text.lower(), text)


def _runs_from_wire(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, (list, tuple)):
        raise RuntimeError("sase_core_rs fuzzy_match returned invalid runs")

    runs: list[tuple[int, int]] = []
    for raw_run in value:
        if (
            not isinstance(raw_run, (list, tuple))
            or len(raw_run) != 2
            or not all(isinstance(offset, int) for offset in raw_run)
        ):
            raise RuntimeError("sase_core_rs fuzzy_match returned invalid runs")
        start, end = cast(tuple[int, int], tuple(raw_run))
        runs.append((start, end))
    return tuple(runs)


__all__ = [
    "FuzzyMatch",
    "fuzzy_match",
    "fuzzy_sort_key",
]
