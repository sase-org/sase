"""Language table and Markdown rows for the Projects language breakdown."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.project_accents import project_accent
from sase.stats.project.languages import (
    LanguageBreakdown,
    LanguageRow,
    LanguageSlice,
)
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._languages_shared import language_color
from sase.stats.render._text import DIM, UNKNOWN_STYLE, square_glyph
from sase.stats.render.context import RenderContext
from sase.stats.render.languages_identity import language_label, language_share_label
from sase.stats.render.primitives import fine_bar, format_count


def _language_table_columns(ctx: RenderContext) -> tuple[bool, bool, int]:
    show_files = ctx.width >= 80
    show_bar = ctx.width >= 100
    bar_width = 24 if ctx.width >= 120 else 16 if ctx.width >= 100 else 0
    return show_files, show_bar, bar_width


def render_language_table(view: ProjectStatsView, ctx: RenderContext) -> RenderableType:
    """Render the Language → Repo tree for one project or the portfolio."""
    from sase.stats.project.languages import language_breakdown

    title = "BY LANGUAGE · source + test lines at each code repo's default-branch tip"
    if view.code_pending:
        table = _plain_table(ctx, title)
        table.add_column("LANGUAGE", ratio=1)
        table.add_row(Text("measuring code…", style="dim italic"))
        return table
    subject_code = (
        view.portfolio.code
        if len(view.projects) > 1
        else view.projects[0].code
        if view.projects
        else None
    )
    if subject_code is None:
        table = _plain_table(ctx, title)
        table.add_column("LANGUAGE", ratio=1)
        table.add_row(Text("Code could not be measured; see Issues below.", style=DIM))
        return table
    breakdown = language_breakdown(view)
    if breakdown is None:
        table = _plain_table(ctx, title)
        table.add_column("LANGUAGE", ratio=1)
        table.add_row(Text("Code could not be measured; see Issues below.", style=DIM))
        return table
    languages_missing = subject_code.languages is None
    if languages_missing:
        table = _plain_table(ctx, title)
        table.add_column("LANGUAGE", ratio=1)
        table.add_row(Text("No language data in this report.", style=DIM))
        return table
    if breakdown.total_lines == 0 or (
        breakdown.measured_repos == 0 and not breakdown.rows
    ):
        table = _plain_table(ctx, title)
        table.add_column("LANGUAGE", ratio=1)
        table.add_row(Text("No code lines measured.", style=DIM))
        unclassified_note = _unclassified_table_note(breakdown)
        if unclassified_note is not None:
            return Group(table, unclassified_note)
        return table

    show_files, show_bar, bar_width = _language_table_columns(ctx)
    table = _plain_table(ctx, title)
    table.add_column(
        "LANGUAGE", min_width=10, ratio=1, no_wrap=True, overflow="ellipsis"
    )
    table.add_column("LINES", justify="right", no_wrap=True)
    if show_files:
        table.add_column("FILES", justify="right", no_wrap=True)
    table.add_column("SHARE", justify="right", no_wrap=True)
    if show_bar:
        table.add_column("", no_wrap=True)

    scale = max([row.lines for row in breakdown.rows] or [1])
    for row in breakdown.rows:
        _add_language_row(
            table, breakdown, row, ctx, scale, show_files, show_bar, bar_width
        )

    table.add_section()
    total_cells: list[RenderableType] = [Text("total", style="bold")]
    total_cells.append(format_count(breakdown.total_lines))
    if show_files:
        total_cells.append(format_count(breakdown.total_files))
    total_cells.append("100%")
    if show_bar:
        total_cells.append(Text(""))
    table.add_row(*total_cells)

    notes: list[RenderableType] = [table]
    if breakdown.zero_languages:
        parts = ", ".join(
            f"{language_label(item.language)} ({format_count(item.files)} files)"
            if item.files != 1
            else f"{language_label(item.language)} (1 file)"
            for item in breakdown.zero_languages
        )
        notes.append(Text(f"No countable lines: {parts}", style=DIM))
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
        notes.append(Text(f"not measured: {details}", style=DIM))
    unclassified_note = _unclassified_table_note(breakdown)
    if unclassified_note is not None:
        notes.append(unclassified_note)
    if breakdown.overlap_lines > 0:
        notes.append(
            Text(
                f"{format_count(breakdown.overlap_lines)} lines are in repos counted "
                "under more than one project; totals count each once",
                style=DIM,
            )
        )
    if len(notes) == 1:
        return table
    return Group(*notes)


def _unclassified_table_note(breakdown: LanguageBreakdown) -> Text | None:
    """Return the dim ``not counted as code`` note, if the guard fires."""
    unclassified = breakdown.unclassified or ()
    if not unclassified:
        return None
    total = sum(item.lines for item in unclassified)
    if breakdown.many_projects:
        details = ", ".join(
            f"{item.project_label} · {item.repo_name} {format_count(item.lines)}"
            for item in unclassified
        )
    else:
        details = ", ".join(
            f"{item.repo_name} {format_count(item.lines)}" for item in unclassified
        )
    return Text(
        f"not counted as code: {format_count(total)} lines in files "
        f"with no recognized language ({details})",
        style=DIM,
    )


def _plain_table(ctx: RenderContext, title: str) -> Table:
    from rich import box

    return Table(
        box=box.SIMPLE if ctx.unicode else box.ASCII,
        expand=True,
        pad_edge=False,
        show_edge=False,
        title=Text(title, style="bold"),
        title_justify="left",
    )


def _add_language_row(
    table: Table,
    breakdown: LanguageBreakdown,
    row: LanguageRow,
    ctx: RenderContext,
    scale: int,
    show_files: bool,
    show_bar: bool,
    bar_width: int,
) -> None:
    if row.language is None:
        name = Text("?  no language detected", style=UNKNOWN_STYLE)
        color = UNKNOWN_STYLE
    else:
        label = language_label(row.language)
        color = language_color(row.language)
        name = Text()
        if ctx.unicode:
            name.append("● ", style=color)
        name.append(label, style="bold")
    share = language_share_label(row.lines, breakdown.total_lines)
    cells: list[RenderableType] = [name, format_count(row.lines)]
    if show_files:
        cells.append(format_count(row.files))
    cells.append(share)
    if show_bar:
        cells.append(
            fine_bar(
                row.lines,
                scale,
                width=bar_width,
                style=color,
                ascii_fallback=not ctx.unicode,
            )
        )
    # Collapsed single-repo language: parent carries the repo name.
    if (
        row.language is not None
        and len(row.slices) == 1
        and not breakdown.many_projects
    ):
        only = row.slices[0]
        name.append(f"  {only.repo_name}", style=DIM)
        table.add_row(*cells)
        return
    if row.language is not None and len(row.slices) <= 1 and breakdown.many_projects:
        # Single slice in a portfolio still renders as collapsed project label.
        if len(row.slices) == 1:
            only = row.slices[0]
            name.append("  ", style="")
            name.append_text(_portfolio_owner_text(only, ctx, single=True))
            table.add_row(*cells)
            return
    table.add_row(*cells)
    if not row.slices:
        return
    # When only one repo holds the lines but many repos exist, collapse already
    # handled above; otherwise list up to 3 children plus a folded row.
    if row.language is not None and len(row.slices) == 1:
        return
    children = list(row.slices[:3])
    hidden = list(row.slices[3:])
    for child in children:
        table.add_row(
            *_child_cells(
                breakdown, row, child, ctx, show_files, show_bar, bar_width, scale
            )
        )
    if hidden:
        folded_lines = sum(item.lines for item in hidden)
        folded_files = sum(item.files for item in hidden)
        folded_label = Text(f"    +{len(hidden)} more repos", style=DIM)
        folded_cells: list[RenderableType] = [
            folded_label,
            format_count(folded_lines),
        ]
        if show_files:
            folded_cells.append(format_count(folded_files))
        folded_cells.append(language_share_label(folded_lines, breakdown.total_lines))
        if show_bar:
            folded_cells.append(
                fine_bar(
                    folded_lines,
                    scale,
                    width=bar_width,
                    style=color + " dim" if not color.startswith("dim") else color,
                    ascii_fallback=not ctx.unicode,
                )
            )
        table.add_row(*folded_cells, style=DIM)


def _child_cells(
    breakdown: LanguageBreakdown,
    row: LanguageRow,
    child: LanguageSlice,
    ctx: RenderContext,
    show_files: bool,
    show_bar: bool,
    bar_width: int,
    scale: int,
) -> tuple[RenderableType, ...]:
    color = language_color(row.language)
    if breakdown.many_projects:
        name = Text("    ")
        name.append_text(_portfolio_owner_text(child, ctx, single=False))
    else:
        name = Text(f"    {child.repo_name}", style=DIM)
    cells: list[RenderableType] = [name, format_count(child.lines)]
    if show_files:
        cells.append(format_count(child.files))
    cells.append(language_share_label(child.lines, breakdown.total_lines))
    if show_bar:
        style = color + " dim" if not color.startswith("dim") else color
        cells.append(
            fine_bar(
                child.lines,
                max(scale, 1),
                width=bar_width,
                style=style,
                ascii_fallback=not ctx.unicode,
            )
        )
    return tuple(cells)


def _portfolio_owner_text(
    child: LanguageSlice, ctx: RenderContext, *, single: bool
) -> Text:
    accent = project_accent(child.project_key, among=(child.project_key,))
    text = Text()
    text.append(f"{square_glyph(ctx)} ", style=accent)
    text.append(child.project_label, style="bold")
    # Mirror _collapsed_tree_row: single-code-repo projects collapse to the
    # project label, appending the repo only when the names differ.
    text.append(f" · {child.repo_name}", style=DIM)
    return text


def language_markdown_rows(
    breakdown: LanguageBreakdown,
) -> list[tuple[str, int, int, str, bool, bool]]:
    """Return (name, lines, files, share, indented, dimmed) rows for Markdown."""
    rows: list[tuple[str, int, int, str, bool, bool]] = []
    for row in breakdown.rows:
        label = (
            "? no language detected"
            if row.language is None
            else language_label(row.language)
        )
        share = language_share_label(row.lines, breakdown.total_lines)
        if (
            row.language is not None
            and len(row.slices) == 1
            and not breakdown.many_projects
        ):
            only = row.slices[0]
            rows.append(
                (
                    f"{label} · {only.repo_name}",
                    row.lines,
                    row.files,
                    share,
                    False,
                    False,
                )
            )
            continue
        rows.append((label, row.lines, row.files, share, False, False))
        if len(row.slices) <= 1:
            continue
        if row.language is not None and len(row.slices) == 1:
            continue
        for child in row.slices[:3]:
            if breakdown.many_projects:
                child_label = f"{child.project_label} · {child.repo_name}"
            else:
                child_label = child.repo_name
            child_share = language_share_label(child.lines, breakdown.total_lines)
            rows.append(
                (child_label, child.lines, child.files, child_share, True, False)
            )
        hidden = row.slices[3:]
        if hidden:
            folded_lines = sum(item.lines for item in hidden)
            folded_files = sum(item.files for item in hidden)
            folded_share = language_share_label(folded_lines, breakdown.total_lines)
            rows.append(
                (
                    f"+{len(hidden)} more repos",
                    folded_lines,
                    folded_files,
                    folded_share,
                    True,
                    True,
                )
            )
    return rows


__all__ = [
    "language_markdown_rows",
    "render_language_table",
]
