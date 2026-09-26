"""Facade for the shared Rust editor fuzzy matcher."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.core.rust import require_rust_binding


@dataclass(frozen=True, slots=True)
class FuzzyMatch:
    """Shared fuzzy match result using character-indexed match runs."""

    tier: int
    score: int
    runs: tuple[tuple[int, int], ...]


_FUZZY_MATCH_BINDING: Any = None


def _fuzzy_match_binding() -> Any:
    """Return the cached ``sase_core_rs.fuzzy_match`` binding.

    The extension module is stable for the life of the process (a stale
    wheel surfaces at import/first-use and is fixed by reinstall + restart),
    so resolving once per process is exact and skips a repeated
    ``importlib`` round-trip on every scored row.
    """
    global _FUZZY_MATCH_BINDING  # noqa: PLW0603
    binding = _FUZZY_MATCH_BINDING
    if binding is None:
        binding = require_rust_binding("fuzzy_match")
        _FUZZY_MATCH_BINDING = binding
    return binding


def fuzzy_tier_score(query: str, text: str) -> tuple[int, int] | None:
    """Return ``(tier, score)`` for *query* against *text*, or ``None``.

    Scoring-only equivalent of :func:`fuzzy_match` for batch passes over
    thousands of rows: identical tier/score values without per-row result
    allocation or wire-shape validation.
    """
    raw = _fuzzy_match_binding()(query, text)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise RuntimeError("sase_core_rs fuzzy_match returned a non-mapping result")
    return (int(raw["tier"]), int(raw["score"]))


def fuzzy_match(
    query: str, text: str, *, include_runs: bool = True
) -> FuzzyMatch | None:
    """Fuzzy-match *query* against *text* through ``sase_core_rs``.

    Pass ``include_runs=False`` for scoring-only callers: tier and score
    are identical while skipping per-run tuple materialization, which
    dominates batch scoring over thousands of rows.
    """
    raw = _fuzzy_match_binding()(query, text)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise RuntimeError("sase_core_rs fuzzy_match returned a non-mapping result")
    return FuzzyMatch(
        tier=int(raw["tier"]),
        score=int(raw["score"]),
        runs=_runs_from_wire(raw.get("runs")) if include_runs else (),
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
