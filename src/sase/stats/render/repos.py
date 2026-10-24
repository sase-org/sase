"""Repo commit breakdowns and repo-oriented views for the Projects report."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.project_accents import project_accent
from sase.stats.project.models import ProjectStatsProject, ProjectStatsRepo
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._text import (
    DASH,
    DIM,
    agent_share_cell,
    format_ts,
    maybe_int,
    not_counted_label,
    range_heading,
    repo_commits_cell,
    share_of,
    square_glyph,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import fine_bar, format_count


@dataclass(frozen=True, slots=True)
class _RepoCommitRow:
    name: str
    kind: str
    commits: int
    partial: bool
    share: float


@dataclass(frozen=True, slots=True)
class RepoHiddenRow:
    hidden_count: int
    commits: int
    share: float


@dataclass(frozen=True, slots=True)
class _RepoUnmeasuredRow:
    name: str
    reason: str


type _RepoActiveRow = _RepoCommitRow | RepoHiddenRow
type RepoTableRow = tuple[RenderableType, ...]


@dataclass(frozen=True, slots=True)
class _RepoCommitBreakdown:
    active: tuple[_RepoActiveRow, ...]
    unmeasured: tuple[_RepoUnmeasuredRow, ...]
    quiet: tuple[str, ...]
    shared_commits: int


def repo_sort_key(repo: ProjectStatsRepo) -> tuple[int, bool, str, str]:
    commits = (
        repo.output.commits
        if repo.status in {"ok", "partial"}
        and repo.output is not None
        and repo.output.commits is not None
        else 0
    )
    return (-commits, repo.kind != "primary", repo.name.casefold(), repo.id)


def repo_commit_breakdown(
    project: ProjectStatsProject, *, max_rows: int
) -> _RepoCommitBreakdown | None:
    """Build the shared, code-repo-only commit breakdown for one project."""
    code_repos = tuple(repo for repo in project.repos if repo.tier == "code")
    if len(code_repos) < 2 or project.output is None or project.output.commits is None:
        return None

    unmeasured: list[_RepoUnmeasuredRow] = []
    quiet: list[str] = []
    active: list[ProjectStatsRepo] = []
    for repo in code_repos:
        if repo.status not in {"ok", "partial"} or repo.output is None:
            reason = repo.issue.message if repo.issue is not None else repo.status
            unmeasured.append(_RepoUnmeasuredRow(repo.name, reason))
            continue
        commits = repo.output.commits
        if commits is None:
            reason = repo.issue.message if repo.issue is not None else repo.status
            unmeasured.append(_RepoUnmeasuredRow(repo.name, reason))
            continue
        if commits > 0:
            active.append(repo)
        elif commits == 0:
            quiet.append(repo.name)

    active.sort(key=repo_sort_key)
    denominator = sum(repo.output.commits or 0 for repo in active if repo.output)
    all_rows = [
        _RepoCommitRow(
            name=repo.name,
            kind=repo.kind,
            commits=repo.output.commits or 0,
            partial=repo.status == "partial",
            share=(repo.output.commits or 0) / denominator if denominator else 0.0,
        )
        for repo in active
        if repo.output is not None
    ]

    cap = max(1, max_rows)
    if len(all_rows) > cap:
        visible = all_rows[: max(0, cap - 1)]
        hidden = all_rows[len(visible) :]
        hidden_commits = sum(row.commits for row in hidden)
        active_rows: tuple[_RepoActiveRow, ...] = tuple(visible) + (
            RepoHiddenRow(
                hidden_count=len(hidden),
                commits=hidden_commits,
                share=hidden_commits / denominator if denominator else 0.0,
            ),
        )
    else:
        active_rows = tuple(all_rows)

    total_active_commits = sum(row.commits for row in all_rows)
    shared = max(0, total_active_commits - project.output.commits)
    return _RepoCommitBreakdown(
        active=active_rows,
        unmeasured=tuple(unmeasured),
        quiet=tuple(quiet),
        shared_commits=shared,
    )


def render_repo_breakdown(
    breakdown: _RepoCommitBreakdown,
    ctx: RenderContext,
    accent: str,
) -> RenderableType:
    """Render the compact one-project card block."""
    if ctx.width >= 100:
        name_cap, bar_width = 28, 24
    elif ctx.width >= 80:
        name_cap, bar_width = 22, 14
    elif ctx.width >= 60:
        name_cap, bar_width = 16, 10
    else:
        name_cap, bar_width = 12, 0

    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(max_width=name_cap, no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column(justify="right", no_wrap=True)
    if bar_width:
        table.add_column(width=bar_width, no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)

    active_commits = [row.commits for row in breakdown.active]
    max_commits = max(active_commits, default=0)
    for row in breakdown.active:
        if isinstance(row, RepoHiddenRow):
            name = Text(f"+{row.hidden_count} more repos", style=DIM)
            count = format_count(row.commits)
            partial_note = Text()
        else:
            name = (
                Text(row.name, style="bold")
                if row.kind == "primary"
                else Text(row.name)
            )
            count = (
                f"≥{format_count(row.commits)}"
                if row.partial
                else format_count(row.commits)
            )
            partial_note = (
                Text("partial history", style=DIM)
                if row.partial and ctx.width >= 80
                else Text()
            )
        percent = round(row.share * 100)
        share = "<1%" if row.share > 0 and percent == 0 else f"{percent}%"
        cells: list[RenderableType] = [name, count]
        if bar_width:
            cells.append(
                fine_bar(
                    row.commits,
                    max_commits,
                    width=bar_width,
                    style=accent,
                    ascii_fallback=not ctx.unicode,
                )
            )
        cells.extend([Text(share, style=DIM), partial_note])
        table.add_row(*cells, style=DIM if isinstance(row, RepoHiddenRow) else None)

    for unmeasured in breakdown.unmeasured:
        unmeasured_cells: list[RenderableType] = [
            Text(unmeasured.name, style=DIM),
            DASH,
        ]
        if bar_width:
            unmeasured_cells.append(Text(" " * bar_width))
        unmeasured_cells.extend(
            [Text("", style=DIM), Text(f"not measured: {unmeasured.reason}", style=DIM)]
        )
        table.add_row(*unmeasured_cells, style=DIM)

    notes: list[RenderableType] = [table]
    if breakdown.quiet:
        names = list(breakdown.quiet[:6])
        if len(breakdown.quiet) > 6:
            names.append(f"+{len(breakdown.quiet) - 6} more")
        notes.append(
            Text(
                "no commits in range: " + ", ".join(names),
                style=DIM,
                no_wrap=True,
                overflow="ellipsis",
            )
        )
    if breakdown.shared_commits > 0:
        notes.append(
            Text(
                f"{format_count(breakdown.shared_commits)} commits are in more than one repo; "
                "the total counts each once",
                style=DIM,
                no_wrap=True,
                overflow="ellipsis",
            )
        )
    return Group(*notes)


def _table(*, ctx: RenderContext, title: str) -> Table:
    table = Table(
        box=box.SIMPLE if ctx.unicode else box.ASCII,
        expand=True,
        pad_edge=False,
        show_edge=False,
        title=Text(title, style="bold"),
        title_justify="left",
    )
    return table


def _project_cell(project: ProjectStatsProject, ctx: RenderContext) -> Text:
    accent = project_accent(project.key, among=(project.key,))
    text = Text()
    text.append(f"{square_glyph(ctx)} ", style=accent)
    text.append(project.label, style="bold")
    if project.state == "unregistered":
        text.append(" (unregistered)", style=DIM)
    elif project.state == "disabled":
        text.append(" (disabled)", style=DIM)
    return text


def _status_name(repo: ProjectStatsRepo, *, indent: bool = False) -> Text:
    name = Text(("    " if indent else "") + repo.name)
    if repo.status != "ok":
        reason = repo.issue.message if repo.issue is not None else repo.status
        name.append(f"  {reason}", style=DIM)
    return name


def _project_sort_key(project: ProjectStatsProject) -> tuple[float, str, str]:
    commits = None if project.output is None else project.output.commits
    return (
        float("inf") if commits is None else -commits,
        project.label.casefold(),
        project.key,
    )


def _repo_snapshot_cells(repo: ProjectStatsRepo) -> tuple[str, str, str, str, str]:
    snapshot = repo.snapshot
    output = repo.output
    return (
        repo_commits_cell(repo),
        agent_share_cell(output),
        maybe_int(None if snapshot is None else snapshot.tracked_lines),
        DASH
        if snapshot is None
        else share_of(snapshot.test_lines, snapshot.tracked_lines),
        maybe_int(None if snapshot is None else snapshot.doc_lines),
    )


def _repo_date_cells(repo: ProjectStatsRepo, ctx: RenderContext) -> tuple[str, str]:
    lifetime = repo.lifetime
    return (
        format_ts(
            None if lifetime is None else lifetime.first_commit_ts, ctx, "%b %d, %Y"
        ),
        format_ts(
            None if lifetime is None else lifetime.last_commit_ts, ctx, "%b %d, %Y"
        ),
    )


def _project_tree_cells(
    project: ProjectStatsProject, ctx: RenderContext
) -> RepoTableRow:
    output = project.output
    code = project.code
    lifetime = project.lifetime
    tests = (
        DASH
        if code is None
        else maybe_int(None)
        if code.test_share is None and code.test_lines is None
        else f"{round(code.test_share * 100)}%"
        if code.test_share is not None
        else share_of(code.test_lines, code.code_lines)
    )
    return (
        _project_cell(project, ctx),
        "",
        maybe_int(None if output is None else output.commits),
        agent_share_cell(output),
        maybe_int(None if code is None else code.code_lines),
        tests,
        maybe_int(None if code is None else code.doc_lines),
        format_ts(
            None if lifetime is None else lifetime.first_commit_ts, ctx, "%b %d, %Y"
        ),
        format_ts(
            None if lifetime is None else lifetime.last_commit_ts, ctx, "%b %d, %Y"
        ),
    )


def _collapsed_tree_row(
    project: ProjectStatsProject, repo: ProjectStatsRepo, ctx: RenderContext
) -> RepoTableRow:
    project_name = _project_cell(project, ctx)
    if repo.name != project.label:
        project_name.append(f" · {repo.name}", style=DIM)
    commits, agent, lines, tests, docs = _repo_snapshot_cells(repo)
    first, last = _repo_date_cells(repo, ctx)
    return (
        project_name,
        repo.kind,
        commits,
        agent,
        lines,
        tests,
        docs,
        first,
        last,
    )


def _tree_table(
    view: ProjectStatsView,
    ctx: RenderContext,
    rows: list[RepoTableRow],
    *,
    first_header: str,
) -> Table:
    all_details = ["DOC LINES", "FIRST COMMIT", "LAST COMMIT"]
    details = all_details.copy()
    if not ctx.show_detail_columns:
        details = []
    headers = [
        first_header,
        "KIND",
        "COMMITS",
        "AGENT",
        "CODE LINES",
        "TESTS",
        *details,
    ]
    if not ctx.show_detail_columns:
        rows[:] = [row[:6] for row in rows]
    row_width = max(
        [
            cell_len(str(value.plain if isinstance(value, Text) else value))
            for row in rows
            for value in row[:1]
        ]
        + [cell_len(first_header)]
    )
    name_floor = min(row_width, 24)

    def required() -> int:
        fixed = 0
        for index, header in enumerate(headers[1:], start=1):
            values = [cell_len(header)]
            values.extend(
                cell_len(str(value.plain if isinstance(value, Text) else value))
                for row in rows
                if index < len(row)
                for value in (row[index],)
            )
            fixed += max(values) + 2
        return name_floor + 2 + fixed + max(0, len(headers) - 1)

    for header in tuple(details):
        if required() <= ctx.width:
            break
        index = headers.index(header)
        headers.pop(index)
        details.remove(header)
        rows[:] = [row[:index] + row[index + 1 :] for row in rows]

    table = _table(ctx=ctx, title=f"REPO · {range_heading(view)}")
    table.add_column(
        first_header,
        min_width=name_floor,
        style="bold",
        ratio=1,
        no_wrap=True,
        overflow="ellipsis",
    )
    for header in headers[1:]:
        table.add_column(
            header,
            justify="right" if header != "KIND" else "left",
            no_wrap=True,
        )
    return table


def render_repo_table(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render code repos (as a project tree for portfolios), records, and exclusions."""
    many = len(view.projects) > 1
    code_projects = [
        (
            project,
            sorted(
                (repo for repo in project.repos if repo.tier == "code"),
                key=repo_sort_key,
            ),
        )
        for project in sorted(view.projects, key=_project_sort_key)
        if any(repo.tier == "code" for repo in project.repos)
    ]
    sections: list[RenderableType] = []
    if many:
        row_data: list[RepoTableRow] = []
        row_styles: list[str | None] = []
        for project, repos in code_projects:
            if len(repos) == 1:
                repo = repos[0]
                row_data.append(_collapsed_tree_row(project, repo, ctx))
                row_styles.append(
                    DIM
                    if repo.status != "ok" or repo_commits_cell(repo) == "0"
                    else None
                )
                continue
            row_data.append(_project_tree_cells(project, ctx))
            row_styles.append(None)
            for repo in repos:
                commits, agent, lines, tests, docs = _repo_snapshot_cells(repo)
                first, last = _repo_date_cells(repo, ctx)
                row_data.append(
                    (
                        _status_name(repo, indent=True),
                        repo.kind,
                        commits,
                        agent,
                        lines,
                        tests,
                        docs,
                        first,
                        last,
                    )
                )
                row_styles.append(
                    DIM if repo.status != "ok" or commits in {"0", DASH} else None
                )
        tree = _tree_table(view, ctx, row_data, first_header="PROJECT → REPO")
        for row, style in zip(row_data, row_styles, strict=True):
            tree.add_row(*row, style=style)
        sections.append(tree)
    else:
        rows: list[RepoTableRow] = []
        styles: list[str | None] = []
        if code_projects:
            _project, repos = code_projects[0]
            for repo in repos:
                commits, agent, lines, tests, docs = _repo_snapshot_cells(repo)
                first, last = _repo_date_cells(repo, ctx)
                repo_row: RepoTableRow = (
                    _status_name(repo),
                    repo.kind,
                    commits,
                    agent,
                    lines,
                    tests,
                    docs,
                    first,
                    last,
                )
                rows.append(repo_row)
                styles.append(
                    DIM if repo.status != "ok" or commits in {"0", DASH} else None
                )
        code_table = _tree_table(view, ctx, rows, first_header="REPO")
        for row, style in zip(rows, styles, strict=True):
            code_table.add_row(*row, style=style)
        sections.append(code_table)

    records: list[tuple[ProjectStatsProject, ProjectStatsRepo]] = [
        (project, repo)
        for project in view.projects
        for repo in project.repos
        if repo.tier == "records"
    ]
    if records:
        sections.append(_records_table(view, ctx, records, many=many))

    not_counted = _not_counted_line(view)
    if not_counted is not None:
        sections.append(not_counted)
    return Group(*sections)


def _records_table(
    view: ProjectStatsView,
    ctx: RenderContext,
    repos: list[tuple[ProjectStatsProject, ProjectStatsRepo]],
    *,
    many: bool,
) -> Table:
    details = ["FIRST COMMIT", "LAST COMMIT"] if ctx.show_detail_columns else []
    headers = (["PROJECT"] if many else []) + ["REPO", "COMMITS", "FILES", *details]
    rows: list[RepoTableRow] = []
    for project, repo in sorted(
        repos,
        key=lambda item: (
            -(item[1].output.commits or 0) if item[1].output is not None else 0,
            item[0].label.casefold(),
            item[1].name.casefold(),
            item[1].id,
        ),
    ):
        lifetime = repo.lifetime
        snapshot = repo.snapshot
        commits = None if lifetime is None else lifetime.commits
        if commits is None and snapshot is not None:
            commits = snapshot.lifetime_commits
        row: RepoTableRow = tuple([project.label] if many else []) + (
            _status_name(repo),
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
        )
        rows.append(row)

    if not ctx.show_detail_columns:
        rows[:] = [row[:-2] for row in rows]

    name_index = 1 if many else 0
    name_floor = min(
        24,
        max(
            [cell_len("REPO")]
            + [
                cell_len(value.plain if isinstance(value, Text) else str(value))
                for row in rows
                for value in (row[name_index],)
            ],
        ),
    )

    def required() -> int:
        fixed = 0
        for index, header in enumerate(headers):
            if index == name_index:
                continue
            widths = [cell_len(header)]
            widths.extend(
                cell_len(str(value.plain if isinstance(value, Text) else value))
                for row in rows
                for value in (row[index],)
            )
            fixed += max(widths) + 2
        return name_floor + 2 + fixed + max(0, len(headers) - 1)

    for header in tuple(details):
        if required() <= ctx.width:
            break
        index = headers.index(header)
        headers.pop(index)
        details.remove(header)
        rows[:] = [row[:index] + row[index + 1 :] for row in rows]

    table = _table(ctx=ctx, title="RECORDS · sidecars, never totaled")
    for index, header in enumerate(headers):
        if index == name_index:
            table.add_column(
                header,
                min_width=name_floor,
                style="bold",
                ratio=1,
                no_wrap=True,
                overflow="ellipsis",
            )
        else:
            table.add_column(
                header,
                justify="left" if header == "PROJECT" else "right",
                no_wrap=True,
            )
    for row in rows:
        table.add_row(*row)
    return table


def _not_counted_line(view: ProjectStatsView) -> Text | None:
    items = [
        f"{entry.name} ({not_counted_label(entry.reason)})"
        for project in view.projects
        for entry in project.not_counted
    ]
    return Text("Not counted: " + ", ".join(items), style=DIM) if items else None


__all__ = [
    "RepoHiddenRow",
    "render_repo_breakdown",
    "render_repo_table",
    "repo_commit_breakdown",
    "repo_sort_key",
]
