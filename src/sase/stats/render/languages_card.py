"""Card breakdown grid and language card block for Projects stats."""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from sase.stats.project.languages import (
    LanguageBreakdown,
    LanguageRow,
    UnclassifiedRepo,
)
from sase.stats.render._languages_shared import NEUTRAL_COLOR, language_color
from sase.stats.render._text import DIM, UNKNOWN_STYLE
from sase.stats.render.context import RenderContext
from sase.stats.render.languages_identity import language_label, language_share_label
from sase.stats.render.primitives import fine_bar, format_compact


def breakdown_widths(ctx: RenderContext) -> tuple[int, int]:
    """Return the shared (name cap, bar width) tiers for breakdown grids."""
    if ctx.width >= 100:
        return 28, 24
    if ctx.width >= 80:
        return 22, 14
    if ctx.width >= 60:
        return 16, 10
    return 12, 0


def make_breakdown_grid(ctx: RenderContext) -> Table:
    """Build the shared card breakdown grid so by-repo and by-lang align."""
    name_cap, bar_width = breakdown_widths(ctx)
    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(max_width=name_cap, no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column(justify="right", no_wrap=True)
    if bar_width:
        table.add_column(width=bar_width, no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
    return table


def _language_card_cap(ctx: RenderContext) -> int:
    """Return the max visible language rows (the ? row never counts)."""
    return 4 if ctx.width >= 60 else 3


def render_language_card_block(
    breakdown: LanguageBreakdown,
    ctx: RenderContext,
) -> RenderableType | None:
    """Render the compact card ``by lang`` block, or None when hidden."""
    known = [row for row in breakdown.rows if row.language is not None]
    unknown = [row for row in breakdown.rows if row.language is None]
    unclassified = breakdown.unclassified or ()
    if breakdown.total_lines == 0 and not unclassified:
        return None
    if not known and not unknown and not unclassified:
        return None
    cap = _language_card_cap(ctx)
    visible: list[LanguageRow] = list(known[:cap])
    hidden: list[LanguageRow] = list(known[cap:])
    folded: LanguageRow | None = None
    if hidden:
        keep = max(0, cap - 1)
        visible = list(known[:keep])
        hidden = list(known[keep:])
        folded_lines = sum(row.lines for row in hidden)
        folded_files = sum(row.files for row in hidden)
        folded = LanguageRow(
            language="__folded__",
            lines=folded_lines,
            files=folded_files,
            share=(folded_lines / breakdown.total_lines)
            if breakdown.total_lines
            else 0.0,
            slices=(),
        )
        visible.append(folded)
    scale = max([row.lines for row in visible if row.language != "__folded__"] or [1])
    if folded is not None:
        scale = max(scale, *(row.lines for row in known))
    _name_cap, bar_width = breakdown_widths(ctx)
    table = make_breakdown_grid(ctx)
    for row in visible:
        if row.language == "__folded__":
            name = Text(f"+{len(hidden)} more", style=DIM)
            count = format_compact(row.lines)
            share = language_share_label(row.lines, breakdown.total_lines)
            bar: RenderableType = (
                fine_bar(
                    row.lines,
                    scale,
                    width=bar_width,
                    style=NEUTRAL_COLOR,
                    ascii_fallback=not ctx.unicode,
                )
                if bar_width
                else Text("")
            )
            note = Text(
                ", ".join(language_label(item.language or "") for item in hidden),
                style=DIM,
                overflow="ellipsis",
                no_wrap=True,
            )
            cells: list[RenderableType] = [name, count]
            if bar_width:
                cells.append(bar)
            cells.extend([Text(share, style=DIM), note])
            table.add_row(*cells, style=DIM)
            continue
        assert row.language is not None
        label = language_label(row.language)
        color = language_color(row.language)
        name = Text(label)
        count = format_compact(row.lines)
        share = language_share_label(row.lines, breakdown.total_lines)
        bar_cell: RenderableType = (
            fine_bar(
                row.lines,
                scale,
                width=bar_width,
                style=color,
                ascii_fallback=not ctx.unicode,
            )
            if bar_width
            else Text("")
        )
        note = _card_note_text(breakdown, row, ctx)
        cells = [name, count]
        if bar_width:
            cells.append(bar_cell)
        cells.extend([Text(share, style=DIM), note])
        table.add_row(*cells)
    for row in unknown:
        name = Text("?  no language detected", style=UNKNOWN_STYLE)
        count = format_compact(row.lines)
        share = language_share_label(row.lines, breakdown.total_lines)
        bar_cell = (
            fine_bar(
                row.lines,
                scale,
                width=bar_width,
                style=UNKNOWN_STYLE,
                ascii_fallback=not ctx.unicode,
            )
            if bar_width
            else Text("")
        )
        note = _card_note_text(breakdown, row, ctx)
        cells = [name, count]
        if bar_width:
            cells.append(bar_cell)
        cells.extend([Text(share, style=DIM), note])
        table.add_row(*cells, style=UNKNOWN_STYLE)
    if unclassified:
        total_unclassified = sum(item.lines for item in unclassified)
        uc_name = Text("not counted", style=UNKNOWN_STYLE)
        uc_count = format_compact(total_unclassified)
        uc_note = _unclassified_card_note(breakdown, unclassified)
        uc_cells: list[RenderableType] = [uc_name, uc_count]
        if bar_width:
            uc_cells.append(Text(""))
        uc_cells.extend([Text(""), uc_note])
        table.add_row(*uc_cells, style=UNKNOWN_STYLE)
    return table


def _unclassified_card_note(
    breakdown: LanguageBreakdown,
    unclassified: tuple[UnclassifiedRepo, ...],
) -> Text:
    """Return the dim note for the card ``not counted`` row."""
    names: list[str] = []
    for item in unclassified:
        project_label = getattr(item, "project_label", "")
        repo_name = getattr(item, "repo_name", "")
        if breakdown.many_projects:
            names.append(f"{project_label} · {repo_name}")
        else:
            names.append(f"{repo_name}")
    shown = names[:2]
    extra = len(names) - len(shown)
    suffix = f" +{extra} more" if extra else ""
    joined = ", ".join(shown) + suffix
    if breakdown.many_projects:
        return Text(
            f"unrecognized files · {joined}" if joined else "unrecognized files",
            style=DIM,
        )
    return Text(
        f"unrecognized files · {joined}" if joined else "unrecognized files", style=DIM
    )


def _card_note_text(
    breakdown: LanguageBreakdown, row: LanguageRow, ctx: RenderContext
) -> Text:
    if not row.slices:
        return Text("")
    if not breakdown.many_projects:
        if breakdown.measured_repos <= 1:
            return Text("")
        repo_names = [item.repo_name for item in row.slices]
        unique: list[str] = []
        for name in repo_names:
            if name not in unique:
                unique.append(name)
        shown = unique[:3]
        extra = len(unique) - len(shown)
        suffix = f" +{extra} more" if extra else ""
        return Text(", ".join(shown) + suffix, style=DIM)
    # Portfolio: project labels ordered by that language's lines.
    by_project: dict[str, tuple[str, int]] = {}
    for item in row.slices:
        key = item.project_key
        current = by_project.get(key, (item.project_label, 0))
        by_project[key] = (item.project_label, current[1] + item.lines)
    ordered = sorted(by_project.values(), key=lambda item: -item[1])
    labels = [label for label, _lines in ordered]
    shown = labels[:3]
    extra = len(labels) - len(shown)
    suffix = f" +{extra} more" if extra else ""
    return Text(", ".join(shown) + suffix, style=DIM)


__all__ = [
    "breakdown_widths",
    "make_breakdown_grid",
    "render_language_card_block",
]
