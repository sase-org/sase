"""Shared metric legends for the Admin Center Statistics views."""

from __future__ import annotations

from dataclasses import dataclass

from .statistics_pane_data import StatisticsView


@dataclass(frozen=True, slots=True)
class _MetricLegend:
    """One concise definition displayed beneath a Statistics view."""

    term: str
    meaning: str


VIEW_LEGENDS: dict[StatisticsView, tuple[_MetricLegend, ...]] = {
    "overview": (
        _MetricLegend("Success", "completed ÷ finished runs"),
        _MetricLegend("Delta", "run change vs the preceding equal-length window"),
        _MetricLegend("Tiles", "click to open their detail view"),
    ),
    "runs": (
        _MetricLegend("Outcome share", "share of finished runs"),
        _MetricLegend("Waiting", "paused for prerequisites"),
        _MetricLegend("Retry chains", "linked retry groups"),
        _MetricLegend("Attempts", "retry launches"),
        _MetricLegend("Kills", "terminal retry attempts"),
        _MetricLegend(
            "Committing agents",
            "run records with ≥1 commit",
        ),
    ),
    "projects": (
        _MetricLegend("Success", "completed ÷ all runs"),
        _MetricLegend("Share", "share of runs in range"),
        _MetricLegend("Wall", "summed agent runtime"),
        _MetricLegend("Specs", "distinct ChangeSpecs"),
        _MetricLegend("✓/×", "completed/failed runs"),
        _MetricLegend("Unattributed", "runs with no ChangeSpec"),
    ),
    "providers": (
        _MetricLegend("Share", "share of all runs"),
        _MetricLegend("Success", "completed ÷ all runs"),
        _MetricLegend(
            "Avg runtime",
            "mean among runs with a valid finish/stop duration",
        ),
    ),
    "runtime": (
        _MetricLegend("Runs", "records with a valid finish/stop duration"),
        _MetricLegend("p50/p95", "median / 95th-percentile runtime"),
        _MetricLegend("Share", "share of total runtime"),
        _MetricLegend("In progress", "excluded from duration math"),
    ),
    "activity": (
        _MetricLegend(
            "Agents",
            "distinct agent names that used the skill or memory",
        ),
    ),
    "plans_questions": (
        _MetricLegend(
            "(all projects)",
            "global durable activity the project filter cannot scope",
        ),
    ),
}
__all__ = ["VIEW_LEGENDS"]
