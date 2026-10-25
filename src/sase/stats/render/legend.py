"""Legend and coverage footer for the shared Projects report."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from sase.stats.project.models import ProjectStatsCoverage
from sase.stats.project.view import ProjectStatsView
from sase.stats.registry import PROJECT_REPORT_LEGENDS
from sase.stats.render._text import (
    DIM,
    display_models,
    fetched_at,
    maybe_percent,
    relative_ts,
    unknown_reason_label,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count


_COMPACT_LEGEND_TERMS = ("Commits", "Plans", "Runs", "?", "∅")


def render_legend(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render the compact report legend sourced from PROJECT_REPORT_LEGENDS."""
    selected = tuple(
        entry for entry in PROJECT_REPORT_LEGENDS if entry.term in _COMPACT_LEGEND_TERMS
    )
    note = Text(style=DIM)
    for index, entry in enumerate(selected):
        if index:
            note.append("  ·  ")
        note.append(entry.term, style="bold dim")
        note.append(f" = {entry.meaning}")
    grouping = view.effective_group_by
    others = [
        name
        for name in ("repo", "language", "patch", "model", "project")
        if name != grouping
    ]
    more = Text(
        "More: "
        + " · ".join(f"-g {name}" for name in others)
        + " · -r all · -j        Definitions: sase stats project -h",
        style=DIM,
    )
    if ctx.width < 80:
        return note
    return Group(note, more)


def render_coverage_footer(
    view: ProjectStatsView, ctx: RenderContext
) -> RenderableType:
    """Render model-coverage, clocks, and source caveats."""
    lines = [
        model_coverage_line(view),
        _commits_source_line(view, ctx),
        Text(
            "Plans: first committed to the plan store, credited to the proposing model"
            f" · Runs: this machine ({ctx.machine}) only",
            style=DIM,
        ),
    ]
    issues = [issue for issue in view.issues if issue.message]
    if issues:
        text = Text("Issues: ", style=DIM)
        for index, issue in enumerate(issues):
            if index:
                text.append(" · ", style=DIM)
            where = ".".join(part for part in (issue.project, issue.repo) if part)
            prefix = f"{where}: " if where else ""
            text.append(f"{prefix}{issue.message}", style=DIM)
        lines.append(text)
    return Group(*lines)


def model_coverage_line(view: ProjectStatsView) -> Text:
    coverage = _effective_coverage(view)
    tagged = coverage.agent_tagged_commits
    resolved = coverage.resolved_agent_commits
    unknown = coverage.unknown_agent_commits
    text = Text(style=DIM)
    if not tagged:
        text.append("No agent-tagged commits in range")
        return text
    share = maybe_percent(resolved / tagged if tagged else None)
    text.append(
        f"Model recorded for {format_count(resolved)} of "
        f"{format_count(tagged)} agent commits ({share})"
    )
    if unknown:
        reasons = ", ".join(
            f"{format_count(item.count)} {unknown_reason_label(item.reason)}"
            for item in coverage.unknown_reasons
        )
        if not reasons:
            reasons = unknown_reason_label("page_unpublished")
        text.append(f" · {format_count(unknown)} unresolved: {reasons}")
    return text


def _commits_source_line(view: ProjectStatsView, ctx: RenderContext) -> Text:
    text = Text(
        "Commits: code repos' default branches, by commit time",
        style=DIM,
    )
    stamp = fetched_at(view)
    if stamp is not None:
        text.append(f" · refs fetched {relative_ts(stamp, ctx)} (-F to refresh)")
    else:
        text.append(" · local refs (-F to refresh)")
    return text


def _effective_coverage(view: ProjectStatsView) -> ProjectStatsCoverage:
    coverage = view.coverage
    if coverage.agent_tagged_commits:
        return coverage
    models = display_models(view)
    resolved = sum(row.commits for row in models if row.kind == "resolved")
    unknown = sum(row.commits for row in models if row.kind == "unknown")
    tagged = resolved + unknown
    return ProjectStatsCoverage(
        configured_repos=coverage.configured_repos,
        measured_repos=coverage.measured_repos,
        partial_repos=coverage.partial_repos,
        unavailable_repos=coverage.unavailable_repos,
        agent_tagged_commits=tagged,
        resolved_agent_commits=resolved,
        unknown_agent_commits=unknown,
        unknown_reasons=coverage.unknown_reasons,
    )
