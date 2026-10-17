"""Catalog of Statistics views, groupings, and metric legends.

TUI modules, the Statistics help modal, and later CLI surfaces all read this
registry. View ids stay stable; ``cli_name`` is the singular noun each view
will use on the command line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from sase.stats.perf_query import PerfGroupBy

StatisticsView = Literal[
    "overview",
    "runners",
    "projects",
    "providers",
    "activity",
    "macros",
    "plans_questions",
    "perf",
]
ProjectsGroupBy = Literal["project", "patch", "drilldown"]
MacrosGroupBy = Literal["usage", "model", "project", "pairing"]
_STATISTICS_ACCENT = "#FF87D7"


@dataclass(frozen=True, slots=True)
class MetricLegend:
    """One concise definition displayed beneath a Statistics view."""

    term: str
    meaning: str


@dataclass(frozen=True, slots=True)
class StatisticsGrouping:
    """One grouping strategy a Statistics view can cycle through."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class StatisticsViewSpec:
    """Navigation and caption metadata for one Statistics view."""

    id: StatisticsView
    label: str
    compact_label: str
    micro_label: str
    description: str
    compact_description: str
    cli_name: str = ""
    groupings: tuple[StatisticsGrouping, ...] = ()
    legends: tuple[MetricLegend, ...] = ()


_PROJECTS_GROUPINGS: tuple[StatisticsGrouping, ...] = (
    StatisticsGrouping("project", "By Project"),
    StatisticsGrouping("patch", "By Patch"),
    StatisticsGrouping("drilldown", "Project → Patch"),
)
_MACROS_GROUPINGS: tuple[StatisticsGrouping, ...] = (
    StatisticsGrouping("usage", "By Usage"),
    StatisticsGrouping("model", "By Model"),
    StatisticsGrouping("project", "By Project"),
    StatisticsGrouping("pairing", "Used With"),
)
_PERF_GROUPINGS: tuple[StatisticsGrouping, ...] = (
    StatisticsGrouping("subsystem", "By Subsystem"),
    StatisticsGrouping("provider", "By Provider"),
    StatisticsGrouping("workflow", "By Workflow"),
)


STATISTICS_VIEW_SPECS: tuple[StatisticsViewSpec, ...] = (
    StatisticsViewSpec(
        "overview",
        "Overview",
        "Overview",
        "Ovr",
        (
            "Scan run volume and outcomes, commits, plans, questions, "
            "and trends at a glance."
        ),
        "Scan run outcomes, work totals, and trends.",
        cli_name="overview",
        legends=(
            MetricLegend(
                "Success",
                "Success Rate tile = completed ÷ finished runs; "
                "Top projects column = completed ÷ all runs",
            ),
            MetricLegend("Delta", "run change vs the preceding equal-length window"),
            MetricLegend(
                "Commits",
                "total commits, with distinct committing agents and committing runs",
            ),
            MetricLegend("Tiles", "click to open their detail view"),
        ),
    ),
    StatisticsViewSpec(
        "runners",
        "Runners",
        "Runners",
        "Rnrs",
        (
            "Track runner concurrency, occupancy, idle time, peaks, "
            "and today's global limit."
        ),
        "Track occupancy, peaks, idle time, and limits.",
        cli_name="runner",
        legends=(
            MetricLegend(
                "Runner",
                "the live turn holding a sase agent's slot -- root, serial "
                "child, monitor, or follow-up -- plus each live parallel member",
            ),
            MetricLegend(
                "Window",
                "carry-in/live overlap clipped; slot-releasing question waits excluded",
            ),
            MetricLegend("Zero", "wall time with no eligible runner"),
            MetricLegend("Average", "runner-seconds ÷ analyzed wall time"),
            MetricLegend("All time", "begins at earliest valid runner coverage"),
            MetricLegend(
                "Project",
                "filtered before concurrency; first open seeds current",
            ),
            MetricLegend(
                "Skipped",
                "malformed rows, invalid bounds, missing ends, and user-hidden rows omitted",
            ),
            MetricLegend(
                "Current limit",
                "today's global reference, not historical or project capacity",
            ),
        ),
    ),
    StatisticsViewSpec(
        "projects",
        "Projects",
        "Projects",
        "Proj",
        ("Compare run outcomes, commits, Patches, and wall time across projects."),
        "Compare outcomes, Patches, and wall time.",
        cli_name="project",
        groupings=_PROJECTS_GROUPINGS,
        legends=(
            MetricLegend("Success", "completed ÷ all runs"),
            MetricLegend("Share", "share of runs in range"),
            MetricLegend("Wall", "summed agent runtime"),
            MetricLegend("Patches", "distinct attributed Patches"),
            MetricLegend("✓/×", "completed/failed runs"),
            MetricLegend("Unattributed", "runs with no Patch"),
        ),
    ),
    StatisticsViewSpec(
        "providers",
        "Providers",
        "Providers",
        "Prov",
        (
            "Compare provider, model, and effort usage, success rates, "
            "and average runtime."
        ),
        "Compare model usage, success, and runtime.",
        cli_name="provider",
        legends=(
            MetricLegend("Share", "share of all runs"),
            MetricLegend("Success", "completed ÷ all runs"),
            MetricLegend(
                "Avg runtime",
                "mean among runs with a valid finish/stop duration",
            ),
        ),
    ),
    StatisticsViewSpec(
        "activity",
        "Activity",
        "Activity",
        "Act",
        "See which skills, memories, and workspaces agents use most.",
        "See top skills, memories, and workspaces.",
        cli_name="activity",
        legends=(
            MetricLegend(
                "Agents",
                "distinct agent names that used the skill or memory",
            ),
        ),
    ),
    StatisticsViewSpec(
        "macros",
        "Macros",
        "Macros",
        "Mac",
        (
            "Explore Macro adoption, model and project breakdowns, "
            "pairings, and focused details."
        ),
        "Explore Macro usage, pairings, and focus.",
        cli_name="macro",
        groupings=_MACROS_GROUPINGS,
        legends=(
            MetricLegend("Runs", "runs whose launch prompt referenced the macro"),
            MetricLegend(
                "Refs",
                "references; the same name with different arguments counts twice",
            ),
            MetricLegend("Share", "share of runs that referenced any macro"),
            MetricLegend("Child share", "share of that macro's own runs"),
            MetricLegend("Agents", "distinct agent names"),
            MetricLegend("Used with", "macros referenced by the same run"),
            MetricLegend(
                "Scope",
                "launch-boundary references only; workflow step templates excluded",
            ),
        ),
    ),
    StatisticsViewSpec(
        "plans_questions",
        "Plans & Questions",
        "Plans/Q",
        "P&Q",
        (
            "Review plan decisions, epic structure, and how agents ask "
            "for clarification."
        ),
        "Review plan outcomes, epic shape, and questions.",
        cli_name="plan",
        legends=(
            MetricLegend(
                "Project scope",
                "plans and questions honor the filter (first open seeds current); "
                "skills and memories honor it too, shown on the Activity view",
            ),
        ),
    ),
    StatisticsViewSpec(
        "perf",
        "Perf",
        "Perf",
        "Prf",
        (
            "Assess TUI responsiveness, launch and agent latency, stalls, "
            "and data health."
        ),
        "Assess responsiveness, latency, stalls, and health.",
        cli_name="perf",
        groupings=_PERF_GROUPINGS,
        legends=(
            MetricLegend("p50", "nearest-rank median of the window's samples"),
            MetricLegend(
                "p95",
                "nearest-rank 95th percentile; same method as JKPerfTimer",
            ),
            MetricLegend("Startup", "median visible-ready time; ok < 2s, warn < 5s"),
            MetricLegend("Launch", "p95 total launch time"),
            MetricLegend("Stall", "event-loop or message-pump freeze"),
            MetricLegend(
                "Hitch",
                "freeze ≥ hitch threshold; a stall-level freeze counts as both",
            ),
            MetricLegend(
                "Global",
                "Perf ignores the project filter; its sources have no project labels",
            ),
            MetricLegend(
                "Coverage",
                "how far retained logs and telemetry actually go",
            ),
            MetricLegend(
                "Resolution",
                "raw, 5m, 1h, or mixed — what the store served for this range",
            ),
            MetricLegend(
                "Latency p50/p95",
                "the Latency table and Agent/LLM tiles are interpolated "
                "histogram-bucket estimates, not nearest-rank",
            ),
        ),
    ),
)
STATISTICS_VIEW_BY_ID: dict[StatisticsView, StatisticsViewSpec] = {
    spec.id: spec for spec in STATISTICS_VIEW_SPECS
}
VIEW_ORDER: tuple[StatisticsView, ...] = tuple(
    spec.id for spec in STATISTICS_VIEW_SPECS
)
VIEW_LABELS: dict[StatisticsView, str] = {
    spec.id: spec.label for spec in STATISTICS_VIEW_SPECS
}
VIEW_COMPACT_LABELS: dict[StatisticsView, str] = {
    spec.id: spec.compact_label for spec in STATISTICS_VIEW_SPECS
}
VIEW_MICRO_LABELS: dict[StatisticsView, str] = {
    spec.id: spec.micro_label for spec in STATISTICS_VIEW_SPECS
}
VIEW_DESCRIPTIONS: dict[StatisticsView, str] = {
    spec.id: spec.description for spec in STATISTICS_VIEW_SPECS
}
VIEW_LEGENDS: dict[StatisticsView, tuple[MetricLegend, ...]] = {
    spec.id: spec.legends for spec in STATISTICS_VIEW_SPECS
}

PERF_GROUP_ORDER: tuple[PerfGroupBy, ...] = (
    "subsystem",
    "provider",
    "workflow",
)
PROJECTS_GROUP_ORDER: tuple[ProjectsGroupBy, ...] = (
    "project",
    "patch",
    "drilldown",
)
MACROS_GROUP_ORDER: tuple[MacrosGroupBy, ...] = (
    "usage",
    "model",
    "project",
    "pairing",
)


def validated_statistics_view(value: object) -> StatisticsView | None:
    """Return a catalog-backed Statistics view id, if valid.

    A stored ``xprompts`` id is read as ``macros`` unconditionally.
    """
    if isinstance(value, str):
        migrated = "macros" if value == "xprompts" else value
        if migrated in VIEW_ORDER:
            return migrated  # type: ignore[return-value]
    return None


def statistics_view_supports_grouping(view: StatisticsView) -> bool:
    """Return whether ``view`` exposes a configurable grouping strategy."""
    return bool(STATISTICS_VIEW_BY_ID[view].groupings)


def statistics_group_label(view: StatisticsView, grouping: str) -> str:
    """Return the registry label for ``view``'s ``grouping`` id."""
    for group in STATISTICS_VIEW_BY_ID[view].groupings:
        if group.id == grouping:
            return group.label
    return grouping


def statistics_view_description_text(
    spec: StatisticsViewSpec,
    *,
    width: int,
) -> Text:
    """Render the Statistics caption that fits ``width`` terminal cells."""
    full = Text(f"› {spec.description}", style=_STATISTICS_ACCENT)
    if width <= 0 or full.cell_len <= width:
        return full
    return Text(f"› {spec.compact_description}", style=_STATISTICS_ACCENT)


__all__ = [
    "MACROS_GROUP_ORDER",
    "PERF_GROUP_ORDER",
    "PROJECTS_GROUP_ORDER",
    "STATISTICS_VIEW_BY_ID",
    "STATISTICS_VIEW_SPECS",
    "VIEW_COMPACT_LABELS",
    "VIEW_DESCRIPTIONS",
    "VIEW_LABELS",
    "VIEW_LEGENDS",
    "VIEW_MICRO_LABELS",
    "VIEW_ORDER",
    "MacrosGroupBy",
    "MetricLegend",
    "PerfGroupBy",
    "ProjectsGroupBy",
    "StatisticsGrouping",
    "StatisticsView",
    "StatisticsViewSpec",
    "statistics_group_label",
    "statistics_view_description_text",
    "statistics_view_supports_grouping",
    "validated_statistics_view",
]
