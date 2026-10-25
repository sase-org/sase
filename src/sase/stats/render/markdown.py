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
    agent_share_cell,
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
    repo_commits_cell,
    relative_ts,
    sentinel_name,
    share_of,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.legend import model_coverage_line
from sase.stats.render.primitives import format_count
from sase.stats.render.repos import (
    RepoHiddenRow,
    repo_commit_breakdown,
    repo_sort_key,
)


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


def _group_lines(
    view: ProjectStatsView,
    grouping: str,
    ctx: RenderContext,
) -> list[str]:
    if grouping == "project":
        return _project_markdown(view, ctx)
    if grouping == "repo":
        return _repo_markdown(view, ctx)
    if grouping == "language":
        return _language_markdown(view, ctx)
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
    return ["## By project", ""] + _md_table(headers, rows)


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


def _repo_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = [
        "Repo",
        "Kind",
        "Commits",
        "Agent",
        "Code lines",
        "Tests",
        "Language",
        "Doc lines",
        "First commit",
        "Last commit",
    ]
    many = len(view.projects) > 1
    rows: list[list[str]] = []
    records: list[tuple[ProjectStatsProject, ProjectStatsRepo]] = []
    if many:
        for project in sorted(view.projects, key=_project_md_sort_key):
            code_repos = sorted(
                (repo for repo in project.repos if repo.tier == "code"),
                key=repo_sort_key,
            )
            if not code_repos:
                continue
            if len(code_repos) == 1:
                repo = code_repos[0]
                row = _repo_md_row(repo, ctx)
                row[0] = _project_md_name(project) + (
                    f" · {repo.name}" if repo.name != project.label else ""
                )
                rows.append(row)
                continue
            output = project.output
            code = project.code
            lifetime = project.lifetime
            tests = (
                maybe_percent(code.test_share)
                if code is not None and code.test_share is not None
                else share_of(
                    None if code is None else code.test_lines,
                    None if code is None else code.code_lines,
                )
            )
            rows.append(
                [
                    _project_md_name(project),
                    "",
                    maybe_int(None if output is None else output.commits),
                    agent_share_cell(output),
                    maybe_int(None if code is None else code.code_lines),
                    tests,
                    _project_md_language_cell(project),
                    maybe_int(None if code is None else code.doc_lines),
                    format_ts(
                        None if lifetime is None else lifetime.first_commit_ts,
                        ctx,
                        "%b %d, %Y",
                    ),
                    format_ts(
                        None if lifetime is None else lifetime.last_commit_ts,
                        ctx,
                        "%b %d, %Y",
                    ),
                ]
            )
            for repo in code_repos:
                child = _repo_md_row(repo, ctx)
                child[0] = "  " + child[0]
                rows.append(child)
    else:
        single_project = view.projects[0] if view.projects else None
        if single_project is not None:
            for repo in sorted(
                (repo for repo in single_project.repos if repo.tier == "code"),
                key=repo_sort_key,
            ):
                rows.append(_repo_md_row(repo, ctx))
    for project in view.projects:
        records.extend(
            (project, repo) for repo in project.repos if repo.tier == "records"
        )
    if many:
        headers[0] = "Project → Repo"
    lines = ["## By repo", ""] + _md_table(headers, rows)
    if records:
        record_headers = (
            ["Project", "Repo", "Commits", "Files", "First commit", "Last commit"]
            if many
            else ["Repo", "Commits", "Files", "First commit", "Last commit"]
        )
        record_rows = [
            _record_md_row(project, repo, ctx, many=many) for project, repo in records
        ]
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
    from sase.stats.project.languages import repo_code_lines, repo_test_lines
    from sase.stats.render.languages import (
        language_label,
        language_share_label,
        top_language,
    )

    name = repo.name
    if repo.status != "ok":
        reason = repo.issue.message if repo.issue is not None else repo.status
        name = f"{name} ({reason})"
    output = repo.output
    snapshot = repo.snapshot
    lifetime = repo.lifetime
    code_lines = repo_code_lines(snapshot)
    if snapshot is None or code_lines is None:
        lines_text = maybe_int(None)
        tests_text = DASH
        language_text: str = DASH
    else:
        lines_text = maybe_int(code_lines)
        test_lines = repo_test_lines(snapshot)
        if test_lines is None:
            test_lines = snapshot.test_lines
        tests_text = DASH if test_lines is None else share_of(test_lines, code_lines)
        top = top_language(snapshot.languages)
        if top is None:
            language_text = DASH
        else:
            language_text = (
                f"{language_label(top[0])} {language_share_label(top[1], code_lines)}"
            )
    return [
        name,
        repo.kind,
        repo_commits_cell(repo),
        agent_share_cell(output),
        lines_text,
        tests_text,
        language_text,
        maybe_int(None if snapshot is None else snapshot.doc_lines),
        format_ts(
            None if lifetime is None else lifetime.first_commit_ts, ctx, "%b %d, %Y"
        ),
        format_ts(
            None if lifetime is None else lifetime.last_commit_ts, ctx, "%b %d, %Y"
        ),
    ]


def _project_md_language_cell(project: ProjectStatsProject) -> str:
    from sase.stats.render.languages import (
        language_label,
        language_share_label,
        top_language,
    )

    code = project.code
    if code is None or code.code_lines is None or not code.code_lines:
        return DASH
    top = top_language(code.languages)
    if top is None:
        return DASH
    return f"{language_label(top[0])} {language_share_label(top[1], code.code_lines)}"


def _language_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    from sase.stats.project.languages import language_breakdown
    from sase.stats.render.languages import language_label, language_markdown_rows

    if view.code_pending:
        return ["## By language", "", "measuring code…"]
    subject_code = (
        view.portfolio.code
        if len(view.projects) > 1
        else view.projects[0].code
        if view.projects
        else None
    )
    if subject_code is None:
        return ["## By language", "", "Code could not be measured; see Issues below."]
    if subject_code.languages is None:
        return ["## By language", "", "No language data in this report."]
    breakdown = language_breakdown(view)
    if breakdown is None:
        return ["## By language", "", "Code could not be measured; see Issues below."]
    if breakdown.total_lines == 0 or (
        breakdown.measured_repos == 0 and not breakdown.rows
    ):
        return ["## By language", "", "No code lines measured."]
    headers = ["Language", "Lines", "Files", "Share"]
    md_rows = [
        [name, format_count(lang_lines), format_count(lang_files), share]
        for name, lang_lines, lang_files, share, _indented, _dimmed in language_markdown_rows(
            breakdown
        )
    ]
    # Indent child rows like the Rich tree; _md_table escapes pipes already.
    indented_rows: list[list[str]] = []
    for (name, _lang_lines, _lang_files, _share, indented, _dimmed), row in zip(
        language_markdown_rows(breakdown), md_rows, strict=True
    ):
        if indented:
            row[0] = "  " + name
        indented_rows.append(row)
    indented_rows.append(
        [
            "total",
            format_count(breakdown.total_lines),
            format_count(breakdown.total_files),
            "100%",
        ]
    )
    out_lines = ["## By language", ""] + _md_table(headers, indented_rows)
    if breakdown.zero_languages:
        parts = ", ".join(
            f"{language_label(item.language)} ({format_count(item.files)} files)"
            if item.files != 1
            else f"{language_label(item.language)} (1 file)"
            for item in breakdown.zero_languages
        )
        out_lines.extend(["", f"No countable lines: {parts}"])
    if breakdown.unmeasured:
        if breakdown.many_projects:
            details = ", ".join(
                f"{item.project_label} · {item.repo_name} ({item.reason})"
                for item in breakdown.unmeasured
            )
        else:
            details = ", ".join(
                f"{item.repo_name} ({item.reason})" for item in breakdown.unmeasured
            )
        out_lines.extend(["", f"not measured: {details}"])
    if breakdown.overlap_lines > 0:
        out_lines.extend(
            [
                "",
                f"{format_count(breakdown.overlap_lines)} lines are in repos counted "
                "under more than one project; totals count each once",
            ]
        )
    return out_lines


def _project_md_sort_key(project: ProjectStatsProject) -> tuple[float, str, str]:
    commits = None if project.output is None else project.output.commits
    return (
        float("inf") if commits is None else -commits,
        project.label.casefold(),
        project.key,
    )


def _project_md_name(project: ProjectStatsProject) -> str:
    suffix = (
        " (unregistered)"
        if project.state == "unregistered"
        else " (disabled)"
        if project.state == "disabled"
        else ""
    )
    return project.label + suffix


def _record_md_row(
    project: ProjectStatsProject,
    repo: ProjectStatsRepo,
    ctx: RenderContext,
    *,
    many: bool,
) -> list[str]:
    lifetime = repo.lifetime
    snapshot = repo.snapshot
    commits = None if lifetime is None else lifetime.commits
    if commits is None and snapshot is not None:
        commits = snapshot.lifetime_commits
    name = repo.name
    if repo.status != "ok":
        reason = repo.issue.message if repo.issue is not None else repo.status
        name = f"{name} ({reason})"
    row = [
        name,
        maybe_int(commits),
        maybe_int(None if snapshot is None else snapshot.tracked_files),
        format_ts(
            (None if lifetime is None else lifetime.first_commit_ts)
            or (None if snapshot is None else snapshot.first_commit_ts),
            ctx,
            "%b %d, %Y",
        ),
        format_ts(
            (None if lifetime is None else lifetime.last_commit_ts)
            or (None if snapshot is None else snapshot.last_commit_ts),
            ctx,
            "%b %d, %Y",
        ),
    ]
    return [project.label, *row] if many else row


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
