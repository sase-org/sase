"""Replay wire records for the prompt prediction engine.

Split out of :mod:`sase.core.prompt_prediction_wire` to keep each module
under the 500-line cap. Non-replay records live in
:mod:`sase.core.prompt_prediction_wire_prediction`; shared schema
primitives live in :mod:`sase.core._prompt_prediction_wire_shared`. The
public import path remains :mod:`sase.core.prompt_prediction_wire`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core._prompt_prediction_wire_shared import (
    PROMPT_PREDICTION_WIRE_SCHEMA_VERSION,
)
from sase.core._prompt_prediction_wire_shared import require_wire_schema


@dataclass(frozen=True)
class PromptPredictionReplayOptions:
    """Options for the prequential replay evaluator.

    The corpus fields mirror the compile options, the model fields mirror
    the composition config, and ``warm_fraction`` splits the typed rows
    into the warm prefix and the scored suffix.
    """

    schema_version: int = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION
    now_epoch: int = 0
    recency_half_life_days: float = 14.0
    max_context_words: int = 4
    max_successors_per_context: int = 32
    prune_singleton_contexts: bool = False
    excluded_words: list[str] = field(default_factory=list)
    backoff_alpha: float = 0.4
    project_boost: float = 1.0
    draft_weight: float = 1.0
    reject_conflicts: bool = True
    warm_fraction: float = 0.4
    score_every: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for these options."""
        return {
            "schema_version": self.schema_version,
            "now_epoch": self.now_epoch,
            "recency_half_life_days": self.recency_half_life_days,
            "max_context_words": self.max_context_words,
            "max_successors_per_context": self.max_successors_per_context,
            "prune_singleton_contexts": self.prune_singleton_contexts,
            "excluded_words": list(self.excluded_words),
            "backoff_alpha": self.backoff_alpha,
            "project_boost": self.project_boost,
            "draft_weight": self.draft_weight,
            "reject_conflicts": self.reject_conflicts,
            "warm_fraction": self.warm_fraction,
            "score_every": self.score_every,
        }


@dataclass(frozen=True)
class PromptPredictionReplayGateMetrics:
    """Gated metrics for one threshold setting.

    ``precision`` is ``None`` when nothing gated. ``savings`` is the ghost
    keystroke-savings upper bound; ``run_*`` describe the gated-correct
    run-length distribution.
    """

    coverage: float = 0.0
    precision: float | None = None
    savings: float = 0.0
    run_mean: float = 0.0
    run_p95: float = 0.0
    run_max: int = 0


def _prompt_prediction_replay_gate_metrics_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayGateMetrics:
    """Build gate metrics from a Rust wire dict (unversioned record)."""
    precision = data.get("precision")
    return PromptPredictionReplayGateMetrics(
        coverage=float(data.get("coverage", 0.0)),
        precision=None if precision is None else float(precision),
        savings=float(data.get("savings", 0.0)),
        run_mean=float(data.get("run_mean", 0.0)),
        run_p95=float(data.get("run_p95", 0.0)),
        run_max=int(data.get("run_max", 0)),
    )


@dataclass(frozen=True)
class PromptPredictionReplayCohort:
    """One cohort slice: ungated top-1/top-3 plus gated metrics per preset."""

    cohort: str
    positions: int = 0
    top1: float = 0.0
    top3: float = 0.0
    cautious: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )
    balanced: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )
    eager: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )


def _prompt_prediction_replay_cohort_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayCohort:
    """Build a cohort slice from a Rust wire dict (unversioned record)."""
    return PromptPredictionReplayCohort(
        cohort=str(data.get("cohort", "")),
        positions=int(data.get("positions", 0)),
        top1=float(data.get("top1", 0.0)),
        top3=float(data.get("top3", 0.0)),
        cautious=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("cautious", {}))
        ),
        balanced=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("balanced", {}))
        ),
        eager=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("eager", {}))
        ),
    )


@dataclass(frozen=True)
class _PromptPredictionReplaySweepPoint:
    """One threshold-grid point swept without replaying."""

    min_p: float
    min_margin: float
    min_support: int
    coverage: float = 0.0
    precision: float | None = None
    novel_coverage: float = 0.0
    novel_precision: float | None = None


def _prompt_prediction_replay_sweep_point_from_dict(
    data: dict[str, Any],
) -> _PromptPredictionReplaySweepPoint:
    """Build a sweep point from a Rust wire dict (unversioned record)."""
    precision = data.get("precision")
    novel_precision = data.get("novel_precision")
    return _PromptPredictionReplaySweepPoint(
        min_p=float(data["min_p"]),
        min_margin=float(data["min_margin"]),
        min_support=int(data["min_support"]),
        coverage=float(data.get("coverage", 0.0)),
        precision=None if precision is None else float(precision),
        novel_coverage=float(data.get("novel_coverage", 0.0)),
        novel_precision=None if novel_precision is None else float(novel_precision),
    )


@dataclass(frozen=True)
class PromptPredictionReplayMidwordMetrics:
    """Mid-word metrics for one typed-prefix length."""

    k: int = 0
    positions: int = 0
    coverage: float = 0.0
    precision: float | None = None
    savings: float = 0.0


def _prompt_prediction_replay_midword_metrics_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayMidwordMetrics:
    """Build mid-word metrics from a Rust wire dict (unversioned record)."""
    precision = data.get("precision")
    return PromptPredictionReplayMidwordMetrics(
        k=int(data.get("k", 0)),
        positions=int(data.get("positions", 0)),
        coverage=float(data.get("coverage", 0.0)),
        precision=None if precision is None else float(precision),
        savings=float(data.get("savings", 0.0)),
    )


@dataclass(frozen=True)
class PromptPredictionReplayMidwordCohort:
    """One cohort slice of the mid-word report: per-k metrics."""

    cohort: str
    by_k: list[PromptPredictionReplayMidwordMetrics] = field(default_factory=list)


def _prompt_prediction_replay_midword_cohort_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayMidwordCohort:
    """Build a mid-word cohort slice from a Rust wire dict."""
    return PromptPredictionReplayMidwordCohort(
        cohort=str(data.get("cohort", "")),
        by_k=[
            _prompt_prediction_replay_midword_metrics_from_dict(dict(row))
            for row in data.get("by_k", [])
        ],
    )


@dataclass(frozen=True)
class PromptPredictionReplayMidwordPreset:
    """Mid-word completion metrics for one confidence preset."""

    preset: str
    by_k: list[PromptPredictionReplayMidwordMetrics] = field(default_factory=list)
    cohorts: list[PromptPredictionReplayMidwordCohort] = field(default_factory=list)


def _prompt_prediction_replay_midword_preset_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayMidwordPreset:
    """Build a mid-word preset slice from a Rust wire dict."""
    return PromptPredictionReplayMidwordPreset(
        preset=str(data.get("preset", "")),
        by_k=[
            _prompt_prediction_replay_midword_metrics_from_dict(dict(row))
            for row in data.get("by_k", [])
        ],
        cohorts=[
            _prompt_prediction_replay_midword_cohort_from_dict(dict(row))
            for row in data.get("cohorts", [])
        ],
    )


@dataclass(frozen=True)
class PromptPredictionReplayReport:
    """Aggregate-only prequential replay report (never prompt text)."""

    schema_version: int
    rows_total: int = 0
    rows_typed: int = 0
    rows_warmed: int = 0
    rows_scored: int = 0
    positions_total: int = 0
    overall_top1: float = 0.0
    overall_top3: float = 0.0
    cautious: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )
    balanced: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )
    eager: PromptPredictionReplayGateMetrics = field(
        default_factory=PromptPredictionReplayGateMetrics
    )
    cohorts: list[PromptPredictionReplayCohort] = field(default_factory=list)
    sweep: list[_PromptPredictionReplaySweepPoint] = field(default_factory=list)
    latency_us_p50: int = 0
    latency_us_p95: int = 0
    corpus_bytes: int = 0
    corpus_rows_used: int = 0
    corpus_contexts: int = 0
    midword: list[PromptPredictionReplayMidwordPreset] | None = None


def prompt_prediction_replay_report_from_dict(
    data: dict[str, Any],
) -> PromptPredictionReplayReport:
    """Build a report from a Rust wire dict, rejecting schema drift."""
    require_wire_schema(data, "PromptPredictionReplayReport")
    return PromptPredictionReplayReport(
        schema_version=int(data["schema_version"]),
        rows_total=int(data.get("rows_total", 0)),
        rows_typed=int(data.get("rows_typed", 0)),
        rows_warmed=int(data.get("rows_warmed", 0)),
        rows_scored=int(data.get("rows_scored", 0)),
        positions_total=int(data.get("positions_total", 0)),
        overall_top1=float(data.get("overall_top1", 0.0)),
        overall_top3=float(data.get("overall_top3", 0.0)),
        cautious=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("cautious", {}))
        ),
        balanced=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("balanced", {}))
        ),
        eager=_prompt_prediction_replay_gate_metrics_from_dict(
            dict(data.get("eager", {}))
        ),
        cohorts=[
            _prompt_prediction_replay_cohort_from_dict(dict(row))
            for row in data.get("cohorts", [])
        ],
        sweep=[
            _prompt_prediction_replay_sweep_point_from_dict(dict(row))
            for row in data.get("sweep", [])
        ],
        latency_us_p50=int(data.get("latency_us_p50", 0)),
        latency_us_p95=int(data.get("latency_us_p95", 0)),
        corpus_bytes=int(data.get("corpus_bytes", 0)),
        corpus_rows_used=int(data.get("corpus_rows_used", 0)),
        corpus_contexts=int(data.get("corpus_contexts", 0)),
        midword=None
        if data.get("midword") is None
        else [
            _prompt_prediction_replay_midword_preset_from_dict(dict(row))
            for row in data.get("midword", [])
        ],
    )


__all__ = [
    "PromptPredictionReplayCohort",
    "PromptPredictionReplayGateMetrics",
    "PromptPredictionReplayMidwordCohort",
    "PromptPredictionReplayMidwordMetrics",
    "PromptPredictionReplayMidwordPreset",
    "PromptPredictionReplayOptions",
    "PromptPredictionReplayReport",
    "prompt_prediction_replay_report_from_dict",
]
