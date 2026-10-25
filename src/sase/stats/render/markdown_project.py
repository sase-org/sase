"""Markdown project table for the shared Projects report."""

from __future__ import annotations

from sase.stats.project.models import ProjectStatsProject
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._markdown_shared import md_table
from sase.stats.render._text import (
    DASH,
    agent_share_cell,
    format_age_days,
    maybe_int,
    maybe_percent,
    relative_ts,
    share_of,
)
from sase.stats.render.context import RenderContext


def project_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = [
        "Project",
        "Commits",
        "Agent",
        "Plans",
        "Code lines",
        "Tests",
        "Age",
        "Runs",
        "Success",
        "Last commit",
    ]
    rows = [
        _project_md_row(project, ctx)
        for project in sorted(
            view.projects,
            key=lambda project: (
                -(project.output.commits or 0) if project.output else 0,
                project.label.casefold(),
            ),
        )
    ]
    portfolio = view.portfolio
    rows.append(
        [
            "total",
            maybe_int(None if portfolio.output is None else portfolio.output.commits),
            agent_share_cell(portfolio.output),
            maybe_int(
                None if portfolio.output is None else portfolio.output.plans_committed
            ),
            maybe_int(None if portfolio.code is None else portfolio.code.code_lines),
            (
                DASH
                if portfolio.code is None
                else maybe_percent(portfolio.code.test_share)
                if portfolio.code.test_share is not None
                else share_of(portfolio.code.test_lines, portfolio.code.code_lines)
            ),
            format_age_days(
                None if portfolio.lifetime is None else portfolio.lifetime.age_days
            ),
            maybe_int(None if portfolio.runs is None else portfolio.runs.runs),
            maybe_percent(
                None if portfolio.runs is None else portfolio.runs.success_rate
            ),
            relative_ts(
                None
                if portfolio.lifetime is None
                else portfolio.lifetime.last_commit_ts,
                ctx,
            ),
        ]
    )
    return ["## By project", ""] + md_table(headers, rows)


def _project_md_row(project: ProjectStatsProject, ctx: RenderContext) -> list[str]:
    output = project.output
    code = project.code
    runs = project.runs
    lifetime = project.lifetime
    return [
        project.label,
        maybe_int(None if output is None else output.commits),
        agent_share_cell(output),
        maybe_int(None if output is None else output.plans_committed),
        maybe_int(None if code is None else code.code_lines),
        (
            DASH
            if code is None
            else maybe_percent(code.test_share)
            if code.test_share is not None
            else share_of(code.test_lines, code.code_lines)
        ),
        format_age_days(None if lifetime is None else lifetime.age_days),
        maybe_int(None if runs is None else runs.runs),
        maybe_percent(None if runs is None else runs.success_rate),
        relative_ts(None if lifetime is None else lifetime.last_commit_ts, ctx),
    ]


__all__ = [
    "project_markdown",
]
