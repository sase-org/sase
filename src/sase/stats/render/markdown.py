"""GitHub-flavored Markdown renderer for the shared Projects report."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from sase.stats.project.models import (
    ProjectStatsModel,
    ProjectStatsPatch,
    ProjectStatsProject,
    ProjectStatsRepo,
)
from sase.stats.project.query import ProjectStatsGrouping
from sase.stats.project.view import ProjectStatsView
from sase.stats.registry import PROJECT_REPORT_GROUPINGS, PROJECT_REPORT_LEGENDS
from sase.stats.render._text import (
    DASH,
    display_models,
    fetched_at,
    format_age_days,
    format_agent_time,
    format_ts,
    group_models,
    ModelGroup,
    maybe_int,
    maybe_percent,
    not_counted_label,
    range_heading,
    relative_ts,
    sentinel_name,
    share_of,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.legend import model_coverage_line
from sase.stats.render.primitives import format_count


def render_project_stats_markdown(
    view: ProjectStatsView,
    group_by: ProjectStatsGrouping | None,
    *,
    command_line: str,
    versions: Mapping[str, str],
    ctx: RenderContext,
) -> str:
    """Render a pipe-safe Markdown report with no ANSI or box drawing."""
    grouping = group_by or view.effective_group_by
    if grouping not in PROJECT_REPORT_GROUPINGS:
        grouping = view.effective_group_by
    parts = [
        _heading(view),
        "",
        *_card_lines(view, ctx),
        "",
        *_group_lines(view, grouping, ctx),
        "",
        _plain(model_coverage_line(view)),
        _commits_line(view, ctx),
        (
            "Plans: first committed to the plan store, credited to the proposing model"
            f" · Runs: this machine ({ctx.machine}) only"
        ),
        "",
        _legend_lines(),
        "",
        _generated(command_line, versions),
    ]
    return "\n".join(parts).rstrip() + "\n"


def _heading(view: ProjectStatsView) -> str:
    if len(view.projects) == 1:
        title = view.projects[0].label
    else:
        enabled = sum(1 for project in view.projects if project.state == "enabled")
        title = f"SASE projects · {enabled} enabled"
    return f"# {title} · {range_heading(view)}"


def _card_lines(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    subject = view.projects[0] if len(view.projects) == 1 else view.portfolio
    output = subject.output
    if output is None:
        output_line = f"**OUTPUT** {DASH}"
    else:
        share = (
            maybe_percent(output.agent_share)
            if output.agent_share is not None
            else share_of(output.agent_commits, output.commits)
        )
        plans = maybe_int(output.plans_committed)
        output_line = (
            f"**OUTPUT** {maybe_int(output.commits)} commits · {share} by agents"
            f" · {plans} plans committed"
        )
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
    return [output_line, code_line, runs_line]


def _group_lines(
    view: ProjectStatsView,
    grouping: str,
    ctx: RenderContext,
) -> list[str]:
    if grouping == "project":
        return _project_markdown(view, ctx)
    if grouping == "repo":
        return _repo_markdown(view, ctx)
    if grouping == "patch":
        return _patch_markdown(view, ctx)
    return _model_markdown(view, ctx)


def _project_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
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
            (
                DASH
                if portfolio.output is None
                else maybe_percent(portfolio.output.agent_share)
                if portfolio.output.agent_share is not None
                else share_of(portfolio.output.agent_commits, portfolio.output.commits)
            ),
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
    return ["## By project", ""] + _md_table(headers, rows)


def _project_md_row(project: ProjectStatsProject, ctx: RenderContext) -> list[str]:
    output = project.output
    code = project.code
    runs = project.runs
    lifetime = project.lifetime
    return [
        project.label,
        maybe_int(None if output is None else output.commits),
        (
            DASH
            if output is None
            else maybe_percent(output.agent_share)
            if output.agent_share is not None
            else share_of(output.agent_commits, output.commits)
        ),
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


def _repo_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = [
        "Repo",
        "Kind",
        "Commits",
        "Agent",
        "Code lines",
        "Tests",
        "Doc lines",
        "First commit",
        "Last commit",
    ]
    rows = []
    records = []
    for project in view.projects:
        for repo in project.repos:
            row = _repo_md_row(repo, ctx)
            if repo.tier == "records":
                records.append(row)
            else:
                rows.append(row)
    lines = ["## By repo", ""] + _md_table(headers, rows)
    if records:
        record_headers = ["Repo", "Commits", "Files", "First commit", "Last commit"]
        record_rows = [[row[0], row[2], row[4], row[7], row[8]] for row in records]
        lines.extend(["", "### Records", ""] + _md_table(record_headers, record_rows))
    items = [
        f"{entry.name} ({not_counted_label(entry.reason)})"
        for project in view.projects
        for entry in project.not_counted
    ]
    if items:
        lines.extend(["", f"Not counted: {', '.join(items)}"])
    return lines


def _repo_md_row(repo: ProjectStatsRepo, ctx: RenderContext) -> list[str]:
    name = repo.name
    if repo.status != "ok":
        reason = repo.issue.message if repo.issue is not None else repo.status
        name = f"{name} ({reason})"
    output = repo.output
    snapshot = repo.snapshot
    lifetime = repo.lifetime
    return [
        name,
        repo.kind,
        maybe_int(None if output is None else output.commits),
        (
            DASH
            if output is None
            else maybe_percent(output.agent_share)
            if output.agent_share is not None
            else share_of(output.agent_commits, output.commits)
        ),
        maybe_int(None if snapshot is None else snapshot.tracked_lines),
        (
            DASH
            if snapshot is None
            else share_of(snapshot.test_lines, snapshot.tracked_lines)
        ),
        maybe_int(None if snapshot is None else snapshot.doc_lines),
        format_ts(
            None if lifetime is None else lifetime.first_commit_ts, ctx, "%b %d, %Y"
        ),
        format_ts(
            None if lifetime is None else lifetime.last_commit_ts, ctx, "%b %d, %Y"
        ),
    ]


def _model_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = ["Model", "Commits", "Share", "Plans", "Epic", "Tale"]
    groups = group_models(display_models(view))
    total = sum(group.total.commits for group in groups)
    rows: list[list[str]] = []
    for group in groups:
        lead = group.models[0] if group.collapsed else group.total
        rows.append(_model_md_row(lead, group, ctx, total, indent=False))
        if group.collapsed:
            continue
        for row in group.visible_models:
            rows.append(_model_md_row(row, group, ctx, total, indent=True))
        if group.hidden_model_count:
            rows.append([f"+{group.hidden_model_count} more", "", "", "", "", ""])
    rows.append(
        [
            "total",
            format_count(total),
            "100%" if total else DASH,
            maybe_int(_sum(group.total.plans for group in groups)),
            maybe_int(_sum(group.total.plans_epic for group in groups)),
            maybe_int(_sum(group.total.plans_tale for group in groups)),
        ]
    )
    return ["## By model", ""] + _md_table(headers, rows)


def _model_md_row(
    row: ProjectStatsModel,
    group: ModelGroup,
    _ctx: RenderContext,
    total: int,
    *,
    indent: bool,
) -> list[str]:
    if group.kind != "resolved":
        name = sentinel_name(group.kind)
    elif indent:
        name = f"  {row.model or DASH}"
    else:
        name = group.provider or "?"
        if group.collapsed and row.model:
            name = f"{name} · {row.model}"
        if row.model_is_alias:
            name += " (alias)"
    return [
        name,
        format_count(row.commits),
        share_of(row.commits, total or None),
        maybe_int(row.plans),
        maybe_int(row.plans_epic),
        maybe_int(row.plans_tale),
    ]


def _patch_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = [
        "Project → Patch",
        "Runs",
        "✓/×",
        "Run commits",
        "Agent time",
        "Last run",
    ]
    rows: list[list[str]] = []
    for project in view.projects:
        runs = project.runs
        rows.append(
            [
                project.label,
                maybe_int(None if runs is None else runs.runs),
                _ok_fail(
                    None if runs is None else runs.completed,
                    None if runs is None else runs.failed,
                ),
                DASH,
                format_agent_time(None if runs is None else runs.total_runtime_seconds),
                relative_ts(None if runs is None else runs.last_run_ts, ctx),
            ]
        )
        for patch in sorted(project.patches, key=lambda item: (-item.runs, item.name)):
            rows.append(_patch_md_row(patch, ctx))
        unattributed = 0 if runs is None else runs.unattributed_runs
        rows.append(["(no Patch)", format_count(unattributed), DASH, DASH, DASH, DASH])
    return ["## By patch", ""] + _md_table(headers, rows)


def _patch_md_row(patch: ProjectStatsPatch, ctx: RenderContext) -> list[str]:
    name = f"  {patch.name}"
    if patch.has_pr:
        name += " (PR)"
    return [
        name,
        format_count(patch.runs),
        _ok_fail(patch.completed, patch.failed),
        format_count(patch.run_commits),
        format_agent_time(patch.total_runtime_seconds),
        relative_ts(patch.last_run_ts, ctx),
    ]


def _ok_fail(completed: int | None, failed: int | None) -> str:
    if completed is None and failed is None:
        return DASH
    return f"{format_count(completed or 0)}/{format_count(failed or 0)}"


def _legend_lines() -> str:
    compact = {"Commits", "Plans", "Runs", "?", "∅"}
    parts = [
        f"**{entry.term}** = {entry.meaning}"
        for entry in PROJECT_REPORT_LEGENDS
        if entry.term in compact
    ]
    return " · ".join(parts)


def _commits_line(view: ProjectStatsView, ctx: RenderContext) -> str:
    stamp = fetched_at(view)
    suffix = (
        f" · refs fetched {relative_ts(stamp, ctx)} (-F to refresh)"
        if stamp is not None
        else " · local refs (-F to refresh)"
    )
    return "Commits: code repos' default branches, by commit time" + suffix


def _generated(command_line: str, versions: Mapping[str, str]) -> str:
    command = _md_cell(command_line)
    extras = " · ".join(f"{name} {value}" for name, value in versions.items())
    body = f"Generated by `{command}`"
    if extras:
        body += f" · {extras}"
    return body


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    escaped_headers = [_md_cell(header) for header in headers]
    align = ["---" if index == 0 else "---:" for index in range(len(headers))]
    lines = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join(align) + " |",
    ]
    for row in rows:
        cells = [_md_cell(cell) for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _md_cell(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _plain(text: object) -> str:
    plain = getattr(text, "plain", None)
    return plain if isinstance(plain, str) else str(text)


def _sum(values: Iterable[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None
