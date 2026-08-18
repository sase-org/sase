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
        _MetricLegend(
            "Success",
            "Success Rate tile = completed ÷ finished runs; "
            "Top projects column = completed ÷ all runs",
        ),
        _MetricLegend("Delta", "run change vs the preceding equal-length window"),
        _MetricLegend(
            "Commits",
            "total commits, with distinct committing agents and committing runs",
        ),
        _MetricLegend("Tiles", "click to open their detail view"),
    ),
    "runners": (
        _MetricLegend(
            "Runner",
            "the live shell holding a sase agent's slot -- root, serial "
            "child, monitor, or follow-up -- plus each live parallel member",
        ),
        _MetricLegend(
            "Window",
            "carry-in/live overlap clipped; slot-releasing question waits excluded",
        ),
        _MetricLegend("Zero", "wall time with no eligible runner"),
        _MetricLegend("Average", "runner-seconds ÷ analyzed wall time"),
        _MetricLegend("All time", "begins at earliest valid runner coverage"),
        _MetricLegend(
            "Project",
            "filtered before concurrency; first open seeds current",
        ),
        _MetricLegend(
            "Skipped",
            "malformed rows, invalid bounds, missing ends, and user-hidden rows omitted",
        ),
        _MetricLegend(
            "Current limit",
            "today's global reference, not historical or project capacity",
        ),
    ),
    "projects": (
        _MetricLegend("Success", "completed ÷ all runs"),
        _MetricLegend("Share", "share of runs in range"),
        _MetricLegend("Wall", "summed agent runtime"),
        _MetricLegend("Patches", "distinct attributed Patches"),
        _MetricLegend("✓/×", "completed/failed runs"),
        _MetricLegend("Unattributed", "runs with no Patch"),
    ),
    "providers": (
        _MetricLegend("Share", "share of all runs"),
        _MetricLegend("Success", "completed ÷ all runs"),
        _MetricLegend(
            "Avg runtime",
            "mean among runs with a valid finish/stop duration",
        ),
    ),
    "activity": (
        _MetricLegend(
            "Agents",
            "distinct agent names that used the skill or memory",
        ),
    ),
    "xprompts": (
        _MetricLegend("Runs", "runs whose launch prompt referenced the xprompt"),
        _MetricLegend(
            "Refs",
            "references; the same name with different arguments counts twice",
        ),
        _MetricLegend("Share", "share of runs that referenced any xprompt"),
        _MetricLegend("Child share", "share of that xprompt's own runs"),
        _MetricLegend("Agents", "distinct agent names"),
        _MetricLegend("Used with", "xprompts referenced by the same run"),
        _MetricLegend(
            "Scope",
            "launch-boundary references only; workflow step templates excluded",
        ),
    ),
    "plans_questions": (
        _MetricLegend(
            "Project scope",
            "plans and questions honor the filter (first open seeds current); "
            "skills and memories honor it too, shown on the Activity view",
        ),
    ),
    "perf": (
        _MetricLegend("p50", "nearest-rank median of the window's samples"),
        _MetricLegend(
            "p95",
            "nearest-rank 95th percentile; same method as JKPerfTimer",
        ),
        _MetricLegend("Startup", "median visible-ready time; ok < 2s, warn < 5s"),
        _MetricLegend("Launch", "p95 total launch time"),
        _MetricLegend("Stall", "event-loop or message-pump freeze"),
        _MetricLegend(
            "Hitch",
            "freeze ≥ hitch threshold; a stall-level freeze counts as both",
        ),
        _MetricLegend(
            "Global",
            "Perf ignores the project filter; its sources have no project labels",
        ),
        _MetricLegend(
            "Coverage",
            "how far retained logs and telemetry actually go",
        ),
        _MetricLegend(
            "Resolution",
            "raw, 5m, 1h, or mixed — what the store served for this range",
        ),
        _MetricLegend(
            "Latency p50/p95",
            "the Latency table and Agent/LLM tiles are interpolated "
            "histogram-bucket estimates, not nearest-rank",
        ),
    ),
}
__all__ = ["VIEW_LEGENDS"]
