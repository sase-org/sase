"""Ratio / speedup helpers for Phase 7 scenario summaries.

Existing benchmarks already write per-scenario summary dicts that look
like ``{"count": ..., "min_*": ..., "median_*": ..., "p95_*": ..., "max_*": ...}``
where ``*`` is either ``ms`` or ``us``. Phase 7D needs ratios across
those summaries without each agent rolling its own parser, so this
module exposes a small, shape-tolerant helper.

The helpers are deliberately format-tolerant rather than format-strict:
- ``median_ms`` and ``median_us`` are both accepted; values are
  internally normalised to seconds.
- ``count == 0`` (skipped scenario) is treated as missing data, not as
  a divide-by-zero failure.

Phase 7B/7C should keep writing whatever shape their existing harness
already emits; the only requirement is that scenario summaries continue
to expose ``median_ms`` or ``median_us`` and a ``count``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


_SECOND_KEYS: tuple[tuple[str, float], ...] = (
    # (key, multiplier_to_seconds)
    ("median_s", 1.0),
    ("median_ms", 1.0e-3),
    ("median_us", 1.0e-6),
    ("median_ns", 1.0e-9),
)


@dataclass(frozen=True)
class ScenarioComparison:
    """Result of comparing a baseline scenario to a candidate scenario."""

    surface: str
    """Surface or operation label (e.g. ``"parse_project_bytes"``)."""

    workload: str
    """Workload label (e.g. ``"synthetic_1000_specs"``)."""

    scenario: str
    """Scenario name (e.g. ``"rust_facade"`` or ``"transition_wip_to_ready"``)."""

    baseline_label: str
    """Human label for the baseline (typically ``"explicit_python"``)."""

    candidate_label: str
    """Human label for the candidate (typically ``"default_rust"``)."""

    baseline_median_s: float | None
    """Baseline median in seconds, or ``None`` if missing/zero count."""

    candidate_median_s: float | None
    """Candidate median in seconds, or ``None`` if missing/zero count."""

    notes: tuple[str, ...] = field(default_factory=tuple)
    """Free-form notes (e.g. ``"baseline missing"`` or ``"both zero"``)."""

    @property
    def ratio(self) -> float | None:
        """``candidate / baseline`` (``< 1`` means candidate is faster).

        Returns ``None`` when either median is missing or non-positive.
        """
        if (
            self.baseline_median_s is None
            or self.candidate_median_s is None
            or self.baseline_median_s <= 0.0
            or self.candidate_median_s < 0.0
        ):
            return None
        return self.candidate_median_s / self.baseline_median_s

    @property
    def speedup(self) -> float | None:
        """``baseline / candidate`` (``> 1`` means candidate is faster).

        Returns ``None`` when either median is missing or non-positive.
        """
        if (
            self.baseline_median_s is None
            or self.candidate_median_s is None
            or self.baseline_median_s < 0.0
            or self.candidate_median_s <= 0.0
        ):
            return None
        return self.baseline_median_s / self.candidate_median_s

    @property
    def percent_delta(self) -> float | None:
        """Percent change of candidate relative to baseline.

        Negative means candidate is faster. Returns ``None`` when the
        ratio is undefined.
        """
        r = self.ratio
        if r is None:
            return None
        return (r - 1.0) * 100.0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for summary artifacts."""
        return {
            "surface": self.surface,
            "workload": self.workload,
            "scenario": self.scenario,
            "baseline_label": self.baseline_label,
            "candidate_label": self.candidate_label,
            "baseline_median_s": self.baseline_median_s,
            "candidate_median_s": self.candidate_median_s,
            "ratio": self.ratio,
            "speedup": self.speedup,
            "percent_delta": self.percent_delta,
            "notes": list(self.notes),
        }


def scenario_median(summary: Mapping[str, Any]) -> float | None:
    """Return the median of a scenario summary in seconds, or ``None``.

    Recognises ``median_s``, ``median_ms``, ``median_us``, and
    ``median_ns`` so existing Phase 1-6 benchmark JSON shapes work
    without conversion. A scenario with ``count == 0`` is treated as
    missing data.
    """
    if not summary:
        return None
    if summary.get("count", None) == 0 or summary.get("count", None) == 0.0:
        return None
    for key, mult in _SECOND_KEYS:
        if key in summary:
            value = summary[key]
            if value is None:
                continue
            try:
                return float(value) * mult
            except (TypeError, ValueError):
                return None
    return None


def compute_speedup(
    *,
    baseline: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    surface: str,
    workload: str,
    scenario: str,
    baseline_label: str = "explicit_python",
    candidate_label: str = "default_rust",
) -> ScenarioComparison:
    """Compare a baseline scenario summary to a candidate scenario summary.

    Either side may be ``None`` (or an empty mapping); the resulting
    :class:`ScenarioComparison` records that as a ``"baseline missing"``
    or ``"candidate missing"`` note and reports an undefined ratio.
    """
    notes: list[str] = []
    base_s = scenario_median(baseline) if baseline else None
    cand_s = scenario_median(candidate) if candidate else None

    if not baseline:
        notes.append("baseline missing")
    elif base_s is None:
        notes.append("baseline median unavailable")
    if not candidate:
        notes.append("candidate missing")
    elif cand_s is None:
        notes.append("candidate median unavailable")

    return ScenarioComparison(
        surface=surface,
        workload=workload,
        scenario=scenario,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        baseline_median_s=base_s,
        candidate_median_s=cand_s,
        notes=tuple(notes),
    )


def summarize_report(
    *,
    surface: str,
    workload: str,
    baseline_scenarios: Mapping[str, Mapping[str, Any]] | None,
    candidate_scenarios: Mapping[str, Mapping[str, Any]] | None,
    baseline_label: str = "explicit_python",
    candidate_label: str = "default_rust",
) -> list[ScenarioComparison]:
    """Compare every scenario name shared by baseline and candidate scenario maps.

    This is the building block Phase 7D will use to roll a per-surface
    JSON artifact into a comparison table without rewriting every
    benchmark. Scenario keys present on only one side are still
    surfaced (with the appropriate ``"... missing"`` note) so a
    Python-only baseline against a Rust-routed candidate does not
    silently drop scenarios.
    """
    base = dict(baseline_scenarios or {})
    cand = dict(candidate_scenarios or {})
    seen: list[str] = []
    for name in base:
        if name not in seen:
            seen.append(name)
    for name in cand:
        if name not in seen:
            seen.append(name)

    return [
        compute_speedup(
            baseline=base.get(name),
            candidate=cand.get(name),
            surface=surface,
            workload=workload,
            scenario=name,
            baseline_label=baseline_label,
            candidate_label=candidate_label,
        )
        for name in seen
    ]
