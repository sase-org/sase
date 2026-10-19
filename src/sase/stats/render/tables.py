"""Project, repo, model, and patch tables for the shared Projects report."""

from __future__ import annotations

from collections.abc import Iterable

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.project_accents import project_accent
from sase.stats.project.models import (
    ProjectStatsModel,
    ProjectStatsPatch,
    ProjectStatsProject,
    ProjectStatsRepo,
)
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._text import (
    CYAN,
    DASH,
    DIM,
    GREEN,
    RED,
    display_models,
    format_age_days,
    format_agent_time,
    format_ts,
    group_models,
    ModelGroup,
    maybe_int,
    maybe_percent,
    not_counted_label,
    provider_plain,
    provider_style,
    range_heading,
    relative_ts,
    sentinel_name,
    sentinel_style,
    share_of,
    square_glyph,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count


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
    text.append(project.label)
    if project.state == "unregistered":
        text.append(" (unregistered)", style=DIM)
    elif project.state == "disabled":
        text.append(" (disabled)", style=DIM)
    return text


def render_project_table(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render the per-project breakdown, or stacked cards below 60 columns."""
    if ctx.stacked:
        return _stacked_projects(view, ctx)
    table = _table(ctx=ctx, title=f"PROJECT · {range_heading(view)}")
    table.add_column("PROJECT", style="bold", min_width=10, ratio=1)
    table.add_column("COMMITS", justify="right")
    table.add_column("AGENT", justify="right")
    table.add_column("PLANS", justify="right")
    table.add_column("CODE LINES", justify="right")
    table.add_column("TESTS", justify="right")
    table.add_column("AGE", justify="right")
    table.add_column("RUNS", justify="right")
    table.add_column("SUCCESS", justify="right")
    if ctx.show_detail_columns:
        table.add_column("LAST COMMIT", justify="right")
    rows = sorted(
        view.projects,
        key=lambda project: (
            -(project.output.commits or 0) if project.output else 0,
            project.label.casefold(),
            project.key,
        ),
    )
    for project in rows:
        table.add_row(*_project_row(project, ctx, include_last=ctx.show_detail_columns))
    table.add_section()
    table.add_row(*_project_total_row(view, ctx, include_last=ctx.show_detail_columns))
    note = Text(
        f"ᵃ runs launched on this machine ({ctx.machine}).",
        style=DIM,
    )
    return Group(table, note)


def _project_row(
    project: ProjectStatsProject, ctx: RenderContext, *, include_last: bool
) -> tuple[RenderableType, ...]:
    output = project.output
    code = project.code
    runs = project.runs
    lifetime = project.lifetime
    cells: list[RenderableType] = [
        _project_cell(project, ctx),
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
    ]
    if include_last:
        cells.append(
            relative_ts(None if lifetime is None else lifetime.last_commit_ts, ctx)
        )
    return tuple(cells)


def _project_total_row(
    view: ProjectStatsView, ctx: RenderContext, *, include_last: bool
) -> tuple[RenderableType, ...]:
    portfolio = view.portfolio
    cells: list[RenderableType] = [
        Text("total", style="bold"),
        *_project_row(
            ProjectStatsProject(
                key="",
                label="total",
                state="enabled",
                output=portfolio.output,
                lifetime=portfolio.lifetime,
                code=portfolio.code,
                runs=portfolio.runs,
            ),
            ctx,
            include_last=include_last,
        )[1:],
    ]
    return tuple(cells)


def _stacked_projects(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    cards: list[RenderableType] = []
    for project in view.projects:
        body = Text()
        output = project.output
        body.append(
            f"{maybe_int(None if output is None else output.commits)} commits · "
        )
        body.append(
            f"{maybe_int(None if output is None else output.plans_committed)} plans"
        )
        runs = project.runs
        if runs is not None:
            body.append(f" · {format_count(runs.runs)} runs")
        cards.append(
            Panel(
                body,
                title=_project_cell(project, ctx),
                border_style=project_accent(project.key, among=(project.key,)),
                box=box.ROUNDED if ctx.unicode else box.ASCII,
                padding=(0, 1),
            )
        )
    return Group(*cards) if cards else Text("No projects in range.", style=DIM)


def render_repo_table(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render code repos, a records section, and the not-counted line."""
    code_repos: list[tuple[ProjectStatsProject, ProjectStatsRepo]] = []
    record_repos: list[tuple[ProjectStatsProject, ProjectStatsRepo]] = []
    for project in view.projects:
        for repo in project.repos:
            bucket = code_repos if repo.tier == "code" else record_repos
            bucket.append((project, repo))
    many = len(view.projects) > 1
    code_table = _table(ctx=ctx, title=f"REPO · {range_heading(view)}")
    if many:
        code_table.add_column("PROJECT", min_width=8)
    code_table.add_column("REPO", style="bold", min_width=10, ratio=1)
    code_table.add_column("KIND", min_width=7)
    code_table.add_column("COMMITS", justify="right")
    code_table.add_column("AGENT", justify="right")
    code_table.add_column("CODE LINES", justify="right")
    code_table.add_column("TESTS", justify="right")
    if ctx.show_detail_columns:
        code_table.add_column("DOC LINES", justify="right")
        code_table.add_column("FIRST COMMIT", justify="right")
        code_table.add_column("LAST COMMIT", justify="right")
    for project, repo in _sorted_repos(code_repos):
        style = DIM if repo.status != "ok" else None
        code_table.add_row(
            *_repo_row(project, repo, ctx, many=many, records=False),
            style=style,
        )
    sections: list[RenderableType] = [code_table]
    if record_repos:
        records = _table(ctx=ctx, title="RECORDS · sidecars, never totaled")
        if many:
            records.add_column("PROJECT", min_width=8)
        records.add_column("REPO", style="bold", ratio=1)
        records.add_column("COMMITS", justify="right")
        records.add_column("FILES", justify="right")
        if ctx.show_detail_columns:
            records.add_column("FIRST COMMIT", justify="right")
            records.add_column("LAST COMMIT", justify="right")
        for project, repo in _sorted_repos(record_repos):
            records.add_row(*_repo_row(project, repo, ctx, many=many, records=True))
        sections.append(records)
    not_counted = _not_counted_line(view)
    if not_counted is not None:
        sections.append(not_counted)
    return Group(*sections)


def _sorted_repos(
    rows: Iterable[tuple[ProjectStatsProject, ProjectStatsRepo]],
) -> list[tuple[ProjectStatsProject, ProjectStatsRepo]]:
    return sorted(
        rows,
        key=lambda item: (
            -(item[1].output.commits or 0) if item[1].output else 0,
            item[0].label.casefold(),
            item[1].name.casefold(),
        ),
    )


def _repo_row(
    project: ProjectStatsProject,
    repo: ProjectStatsRepo,
    ctx: RenderContext,
    *,
    many: bool,
    records: bool,
) -> tuple[RenderableType, ...]:
    name = Text(repo.name)
    if repo.status != "ok":
        reason = repo.issue.message if repo.issue is not None else repo.status
        name.append(f"  {reason}", style=DIM)
    output = repo.output
    snapshot = repo.snapshot
    lifetime = repo.lifetime
    cells: list[RenderableType] = []
    if many:
        cells.append(project.label)
    if records:
        files = None if snapshot is None else snapshot.tracked_files
        commits = None
        if lifetime is not None:
            commits = lifetime.commits
        elif snapshot is not None:
            commits = snapshot.lifetime_commits
        cells.extend(
            [
                name,
                maybe_int(commits),
                maybe_int(files),
            ]
        )
        if ctx.show_detail_columns:
            first = None if lifetime is None else lifetime.first_commit_ts
            last = None if lifetime is None else lifetime.last_commit_ts
            if snapshot is not None:
                first = first or snapshot.first_commit_ts
                last = last or snapshot.last_commit_ts
            cells.extend(
                [
                    format_ts(first, ctx, "%b %d, %Y"),
                    format_ts(last, ctx, "%b %d, %Y"),
                ]
            )
        return tuple(cells)
    cells.extend(
        [
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
        ]
    )
    if ctx.show_detail_columns:
        cells.extend(
            [
                maybe_int(None if snapshot is None else snapshot.doc_lines),
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
    return tuple(cells)


def _not_counted_line(view: ProjectStatsView) -> Text | None:
    items: list[str] = []
    for project in view.projects:
        for entry in project.not_counted:
            items.append(f"{entry.name} ({not_counted_label(entry.reason)})")
    if not items:
        return None
    return Text("Not counted: " + ", ".join(items), style=DIM)


def render_model_table(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render provider subtotals, indented models, and always-on ?/∅ rows."""
    table = _table(ctx=ctx, title=f"BY MODEL · {range_heading(view)}")
    table.add_column("MODEL", min_width=16, ratio=1)
    table.add_column("COMMITS", justify="right")
    table.add_column("SHARE", justify="right")
    table.add_column("PLANS", justify="right")
    if ctx.show_detail_columns:
        table.add_column("EPIC", justify="right")
        table.add_column("TALE", justify="right")
    groups = group_models(display_models(view))
    total = sum(group.total.commits for group in groups)
    for group in groups:
        lead = group.models[0] if group.collapsed else group.total
        table.add_row(*_model_group_row(lead, group, ctx, total, indent=False))
        if group.collapsed:
            continue
        for row in group.visible_models:
            table.add_row(*_model_group_row(row, group, ctx, total, indent=True))
        if group.hidden_model_count:
            more = Text(
                f"                +{group.hidden_model_count} more",
                style=DIM,
            )
            table.add_row(more, *([""] * (5 if ctx.show_detail_columns else 3)))
    table.add_section()
    total_row: list[RenderableType] = [
        Text("total", style="bold"),
        format_count(total),
        "100%" if total else DASH,
        maybe_int(_nullable_sum(group.total.plans for group in groups)),
    ]
    if ctx.show_detail_columns:
        total_row.extend(
            [
                maybe_int(_nullable_sum(group.total.plans_epic for group in groups)),
                maybe_int(_nullable_sum(group.total.plans_tale for group in groups)),
            ]
        )
    table.add_row(*total_row)
    return table


def _model_group_row(
    row: ProjectStatsModel,
    group: ModelGroup,
    ctx: RenderContext,
    total: int,
    *,
    indent: bool,
) -> tuple[RenderableType, ...]:
    name = _model_name(row, group, ctx, indent=indent)
    if row.model_is_alias:
        name.stylize(DIM)
    cells: list[RenderableType] = [
        name,
        format_count(row.commits),
        share_of(row.commits, total or None),
        maybe_int(row.plans),
    ]
    if ctx.show_detail_columns:
        cells.extend([maybe_int(row.plans_epic), maybe_int(row.plans_tale)])
    return tuple(cells)


def _model_name(
    row: ProjectStatsModel, group: ModelGroup, ctx: RenderContext, *, indent: bool
) -> Text:
    if group.kind != "resolved":
        return Text(sentinel_name(group.kind), style=sentinel_style(group.kind))
    if indent:
        model = row.model or DASH
        text = Text("                " + model, style=provider_style(group.provider))
        return text
    text = Text()
    label = provider_plain(group.provider, ctx) or (group.provider or "?")
    text.append(label, style=provider_style(group.provider))
    if group.collapsed and row.model:
        text.append(f"  {row.model}", style=DIM)
    return text


def _nullable_sum(values: Iterable[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def render_patch_tree(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render a Project → Patch tree with this-machine run facts."""
    table = _table(ctx=ctx, title=f"PATCH · {range_heading(view)}")
    table.add_column("PROJECT → PATCH", min_width=16, ratio=1)
    table.add_column("RUNS", justify="right")
    table.add_column("✓/×", justify="right")
    table.add_column("RUN COMMITS", justify="right")
    table.add_column("AGENT TIME", justify="right")
    table.add_column("LAST RUN", justify="right")
    for project in sorted(
        view.projects,
        key=lambda item: (
            -(item.runs.runs if item.runs is not None else 0),
            item.label.casefold(),
            item.key,
        ),
    ):
        runs = project.runs
        table.add_row(
            _project_cell(project, ctx),
            maybe_int(None if runs is None else runs.runs),
            _ok_fail(
                None if runs is None else runs.completed,
                None if runs is None else runs.failed,
            ),
            DASH,
            format_agent_time(None if runs is None else runs.total_runtime_seconds),
            relative_ts(None if runs is None else runs.last_run_ts, ctx),
            style="bold",
        )
        patches = sorted(
            project.patches,
            key=lambda item: (-item.runs, item.name.casefold()),
        )
        for patch in patches:
            table.add_row(*_patch_row(patch, ctx, indent=True))
        unattributed = 0 if runs is None else runs.unattributed_runs
        table.add_row(
            Text("    (no Patch)", style="dim italic"),
            Text(format_count(unattributed), style=DIM),
            Text(DASH, style=DIM),
            Text(DASH, style=DIM),
            Text(DASH, style=DIM),
            Text(DASH, style=DIM),
        )
    omitted = sum(project.truncated_patch_rows for project in view.projects)
    notes: list[RenderableType] = [
        Text(
            f"ᵃ run commits to code repos on this machine ({ctx.machine}).",
            style=DIM,
        )
    ]
    if omitted:
        notes.append(
            Text(
                f"{format_count(omitted)} more Patch rows omitted from the table.",
                style=DIM,
            )
        )
    return Group(table, *notes)


def _patch_row(
    patch: ProjectStatsPatch, ctx: RenderContext, *, indent: bool
) -> tuple[RenderableType, ...]:
    prefix = "    " if indent else ""
    name = Text(f"{prefix}{patch.name}")
    if patch.has_pr:
        name.append("  PR", style=CYAN)
    return (
        name,
        format_count(patch.runs),
        _ok_fail(patch.completed, patch.failed),
        format_count(patch.run_commits),
        format_agent_time(patch.total_runtime_seconds),
        relative_ts(patch.last_run_ts, ctx),
    )


def _ok_fail(completed: int | None, failed: int | None) -> Text:
    if completed is None and failed is None:
        return Text(DASH, style=DIM)
    text = Text()
    text.append(format_count(completed or 0), style=GREEN)
    text.append("/")
    text.append(format_count(failed or 0), style=RED)
    return text
