"""Project and portfolio summary cards for the shared Projects report."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.project_accents import project_accent
from sase.stats.project.models import ProjectStatsPortfolio, ProjectStatsProject
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._text import (
    CYAN,
    DASH,
    GREEN,
    RED,
    STATS_ACCENT,
    agent_share_cell,
    bar_style_for,
    display_models,
    format_age_days,
    format_agent_time,
    format_ts,
    group_models,
    maybe_int,
    maybe_percent,
    project_border_style,
    provider_plain,
    range_heading,
    sentinel_style,
    share_of,
    square_glyph,
)
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count, stacked_bar
from sase.stats.render.repos import repo_commit_breakdown, render_repo_breakdown

_Subject = ProjectStatsProject | ProjectStatsPortfolio


def render_project_card(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render the one-project card, or the portfolio card for several projects."""
    subject: _Subject
    if len(view.projects) == 1:
        subject = view.projects[0]
        title = _project_title(view.projects[0], ctx)
    else:
        subject = view.portfolio
        enabled = sum(1 for project in view.projects if project.state == "enabled")
        title = Text(f"SASE projects · {enabled} enabled", style=f"bold {STATS_ACCENT}")
    body = Table.grid(padding=(0, 1), expand=True)
    body.add_column(style=f"bold {STATS_ACCENT}", no_wrap=True, min_width=8)
    body.add_column(overflow="fold", ratio=1)
    body.add_row("OUTPUT", _output_line(subject))
    if len(view.projects) == 1:
        breakdown = repo_commit_breakdown(view.projects[0], max_rows=_repo_row_cap(ctx))
        if breakdown is not None:
            accent = project_border_style(view)
            body.add_row(
                Text("by repo", style=f"dim {accent}"),
                render_repo_breakdown(breakdown, ctx, accent),
            )
    body.add_row("CODE", _code_line(view, subject, ctx))
    if len(view.projects) == 1:
        lifetime = _lifetime_line(subject, ctx)
        if lifetime is not None:
            body.add_row("", lifetime)
    body.add_row("RUNS", _runs_line(subject, ctx))
    commit_bar = _provider_bar_line(
        view, ctx, metric="commits", label="Commits by provider"
    )
    if commit_bar is not None:
        body.add_row("", commit_bar)
    if len(view.projects) == 1:
        plan_bar = _provider_bar_line(
            view, ctx, metric="plans", label="Plans by provider"
        )
        if plan_bar is not None:
            body.add_row("", plan_bar)
    return Panel(
        body,
        title=title,
        subtitle=Text(range_heading(view), style="dim"),
        subtitle_align="right",
        border_style=project_border_style(view),
        box=box.ROUNDED if ctx.unicode else box.ASCII,
        padding=(0, 1),
        title_align="left",
    )


def _project_title(project: ProjectStatsProject, ctx: RenderContext) -> Text:
    accent = project_accent(project.key, among=(project.key,))
    text = Text()
    text.append(f"{square_glyph(ctx)} ", style=accent)
    text.append(project.label, style="bold")
    return text


def _output_line(subject: _Subject) -> Text:
    output = subject.output
    text = Text()
    if output is None:
        return Text(DASH, style="dim")
    text.append(f"{maybe_int(output.commits)} commits")
    agent_share = agent_share_cell(output)
    if agent_share != DASH:
        text.append(" · ")
        text.append(f"{agent_share} by agents", style=CYAN)
    plans = _plans_phrase(output.plans_committed, output.plans_epic, output.plans_tale)
    if plans:
        text.append(" · ")
        text.append(plans)
    return text


def _repo_row_cap(ctx: RenderContext) -> int:
    return 6 if ctx.width >= 80 else 5 if ctx.width >= 60 else 4


def _plans_phrase(committed: int | None, epic: int | None, tale: int | None) -> str:
    if committed is None:
        return f"{DASH} plans committed"
    if committed == 0:
        return "0 plans committed"
    extra = []
    if epic is not None:
        extra.append(f"{format_count(epic)} epic")
    if tale is not None:
        extra.append(f"{format_count(tale)} tale")
    suffix = f" ({' · '.join(extra)})" if extra else ""
    return f"{format_count(committed)} plans committed{suffix}"


def _code_line(view: ProjectStatsView, subject: _Subject, ctx: RenderContext) -> Text:
    if subject.code is None:
        if view.code_pending:
            return Text("measuring code…", style="dim italic")
        return Text(DASH, style="dim")
    code = subject.code
    parts = Text()
    parts.append(f"{maybe_int(code.code_lines, compact=True)} lines")
    if code.test_share is not None:
        parts.append(f" · {maybe_percent(code.test_share)} tests")
    elif code.test_lines is not None and code.code_lines:
        parts.append(f" · {share_of(code.test_lines, code.code_lines)} tests")
    if ctx.show_detail_columns and code.doc_lines is not None:
        parts.append(f" · {maybe_int(code.doc_lines, compact=True)} doc lines")
    if code.repos_configured:
        parts.append(
            f" · {format_count(code.repos_measured)} of "
            f"{format_count(code.repos_configured)} code repos"
        )
    return parts


def _lifetime_line(subject: _Subject, ctx: RenderContext) -> Text | None:
    lifetime = subject.lifetime
    if lifetime is None:
        return None
    text = Text(style="dim")
    born = format_ts(lifetime.first_commit_ts, ctx, "%b %d, %Y")
    text.append(f"           {born}")
    text.append(f" · {format_age_days(lifetime.age_days, prose=True)}")
    if lifetime.active_days is not None and lifetime.age_days is not None:
        text.append(
            f" · commits on {format_count(lifetime.active_days)} of "
            f"{format_count(lifetime.age_days)} days"
        )
    if lifetime.commits is not None:
        text.append(f" · {format_count(lifetime.commits)} commits all time")
    return text


def _runs_line(subject: _Subject, ctx: RenderContext) -> Text:
    runs = subject.runs
    if runs is None:
        return Text(DASH, style="dim")
    text = Text()
    text.append(f"{format_count(runs.runs)} runs on {ctx.machine}")
    text.append(" · ")
    text.append("✓ ", style=GREEN)
    text.append(format_count(runs.completed), style=GREEN)
    text.append(" ")
    text.append("× ", style=RED)
    text.append(format_count(runs.failed), style=RED)
    if runs.success_rate is not None:
        text.append(f" · {maybe_percent(runs.success_rate)} success")
    text.append(f" · {format_agent_time(runs.total_runtime_seconds)} agent time")
    if runs.distinct_patches:
        text.append(f" · {format_count(runs.distinct_patches)} Patches")
    return text


def _provider_bar_line(
    view: ProjectStatsView,
    ctx: RenderContext,
    *,
    metric: str,
    label: str,
) -> Text | None:
    groups = group_models(display_models(view))
    values: list[tuple[float, str]] = []
    chips: list[_ModelChip] = []
    total = 0
    for group in groups:
        amount = (
            group.total.commits if metric == "commits" else (group.total.plans or 0)
        )
        if metric == "plans" and not amount:
            continue
        total += amount
        chip = _ModelChip(kind=group.kind, provider=group.provider, amount=amount)
        chips.append(chip)
        if amount:
            values.append((float(amount), bar_style_for(group.kind, group.provider)))
    if metric == "plans" and total == 0:
        return None
    width = 24 if ctx.width >= 100 else 16 if ctx.width >= 80 else 10
    parts = tuple((amount / total if total else 0.0, style) for amount, style in values)
    text = Text()
    text.append(f"{label}  ", style="dim")
    text.append_text(stacked_bar(parts, width=width, ascii_fallback=not ctx.unicode))
    text.append("   ")
    for chip in chips:
        if metric == "plans" and chip.amount == 0:
            continue
        text.append_text(_chip_text(chip, ctx))
        text.append("  ")
    return text


@dataclass
class _ModelChip:
    kind: str
    provider: str | None
    amount: int


def _chip_text(chip: _ModelChip, ctx: RenderContext) -> Text:
    text = Text()
    if chip.kind == "resolved":
        label = provider_plain(chip.provider, ctx) or (chip.provider or "?")
        text.append(
            f"{label} {format_count(chip.amount)}",
            style=bar_style_for(chip.kind, chip.provider),
        )
        return text
    glyph = "?" if chip.kind == "unknown" else "∅"
    text.append(f"{glyph} {format_count(chip.amount)}", style=sentinel_style(chip.kind))
    return text
