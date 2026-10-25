"""Markdown repo tables for the shared Projects report."""

from __future__ import annotations

from sase.stats.project.models import ProjectStatsProject, ProjectStatsRepo
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._markdown_shared import md_table
from sase.stats.render._text import (
    DASH,
    agent_share_cell,
    format_ts,
    maybe_int,
    maybe_percent,
    not_counted_label,
    repo_commits_cell,
    share_of,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count
from sase.stats.render.repos import repo_sort_key


def repo_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
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
    lines = ["## By repo", ""] + md_table(headers, rows)
    if records:
        record_headers = (
            ["Project", "Repo", "Commits", "Files", "First commit", "Last commit"]
            if many
            else ["Repo", "Commits", "Files", "First commit", "Last commit"]
        )
        record_rows = [
            _record_md_row(project, repo, ctx, many=many) for project, repo in records
        ]
        lines.extend(["", "### Records", ""] + md_table(record_headers, record_rows))
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


__all__ = [
    "repo_markdown",
]
