"""Markdown card block for the shared Projects report."""

from __future__ import annotations

from sase.stats.project.view import ProjectStatsView
from sase.stats.render._text import (
    DASH,
    agent_share_cell,
    format_agent_time,
    maybe_int,
    maybe_percent,
    share_of,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count
from sase.stats.render.repos import (
    RepoHiddenRow,
    repo_commit_breakdown,
)


def card_lines(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    subject = view.projects[0] if len(view.projects) == 1 else view.portfolio
    output = subject.output
    if output is None:
        output_line = f"**OUTPUT** {DASH}"
    else:
        share = agent_share_cell(output)
        plans = maybe_int(output.plans_committed)
        output_line = f"**OUTPUT** {maybe_int(output.commits)} commits"
        if share != DASH:
            output_line += f" · {share} by agents"
        output_line += f" · {plans} plans committed"
        extra = []
        if output.plans_epic is not None:
            extra.append(f"{format_count(output.plans_epic)} epic")
        if output.plans_tale is not None:
            extra.append(f"{format_count(output.plans_tale)} tale")
        if extra and output.plans_committed is not None:
            output_line += f" ({' · '.join(extra)})"
    if subject.code is None:
        code_line = (
            "**CODE** measuring code…" if view.code_pending else f"**CODE** {DASH}"
        )
    else:
        code = subject.code
        tests = (
            maybe_percent(code.test_share)
            if code.test_share is not None
            else share_of(code.test_lines, code.code_lines)
        )
        repos = ""
        if code.repos_configured:
            repos = (
                f" · {format_count(code.repos_measured)} of "
                f"{format_count(code.repos_configured)} code repos"
            )
        code_line = (
            f"**CODE** {maybe_int(code.code_lines, compact=True)} lines · {tests} tests"
            f"{repos}"
        )
    runs = subject.runs
    if runs is None:
        runs_line = f"**RUNS** {DASH}"
    else:
        runs_line = (
            f"**RUNS** {format_count(runs.runs)} runs on {ctx.machine} · "
            f"✓ {format_count(runs.completed)} × {format_count(runs.failed)} · "
            f"{maybe_percent(runs.success_rate)} success · "
            f"{format_agent_time(runs.total_runtime_seconds)} agent time"
        )
    lines = [output_line]
    if len(view.projects) == 1:
        breakdown = repo_commit_breakdown(
            view.projects[0], max_rows=max(1, len(view.projects[0].repos))
        )
        if breakdown is not None:
            active = []
            for row in breakdown.active:
                if isinstance(row, RepoHiddenRow):
                    continue
                count = (
                    f"≥{format_count(row.commits)}"
                    if row.partial
                    else format_count(row.commits)
                )
                active.append(f"{row.name} {count} ({_repo_share(row.share)})")
            lines.append("**BY REPO** " + (" · ".join(active) if active else DASH))
            if breakdown.quiet:
                lines.append("no commits: " + ", ".join(breakdown.quiet))
            if breakdown.unmeasured:
                details = ", ".join(
                    f"{row.name} ({row.reason})" for row in breakdown.unmeasured
                )
                lines.append("not measured: " + details)
            if breakdown.shared_commits:
                lines.append(
                    f"{format_count(breakdown.shared_commits)} commits are in more than one repo; "
                    "the total counts each once"
                )
    lines.extend([code_line])
    language_line = _card_language_line(view)
    if language_line is not None:
        lines.append(language_line)
    lines.append(runs_line)
    return lines


def _card_language_line(view: ProjectStatsView) -> str | None:
    from sase.stats.project.languages import language_breakdown
    from sase.stats.render.languages import language_label, language_share_label

    if view.code_pending:
        return None
    subject = view.projects[0] if len(view.projects) == 1 else view.portfolio
    if subject.code is None or subject.code.languages is None:
        return None
    if subject.code.code_lines == 0 or subject.code.code_lines is None:
        return None
    breakdown = language_breakdown(view)
    if breakdown is None or not breakdown.rows:
        return None
    parts: list[str] = []
    for row in breakdown.rows:
        if row.language is None:
            parts.append(
                f"? {format_count(row.lines)} "
                f"({language_share_label(row.lines, breakdown.total_lines)})"
            )
            continue
        label = language_label(row.language)
        parts.append(
            f"{label} {format_count(row.lines)} "
            f"({language_share_label(row.lines, breakdown.total_lines)})"
        )
    if not parts:
        return None
    return "**BY LANGUAGE** " + " · ".join(parts)


def _repo_share(share: float) -> str:
    percent = round(share * 100)
    return "<1%" if share > 0 and percent == 0 else f"{percent}%"


__all__ = [
    "card_lines",
]
