"""Language identity and renderers for the Projects language breakdown."""

from __future__ import annotations

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.project_accents import project_accent
from sase.stats.project.languages import (
    LanguageBreakdown,
    LanguageRow,
    LanguageSlice,
    UnclassifiedRepo,
)
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._text import DIM, DASH, UNKNOWN_STYLE, square_glyph
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import fine_bar, format_compact, format_count

_LANGUAGE_LABELS: dict[str, str] = {
    "python": "Python",
    "rust": "Rust",
    "typescript": "TypeScript",
    "tsx": "TSX",
    "javascript": "JavaScript",
    "jsx": "JSX",
    "css": "CSS",
    "html": "HTML",
    "lua": "Lua",
    "sh": "Shell",
    "bash": "Bash",
    "zsh": "Zsh",
    "fish": "Fish",
    "json": "JSON",
    "yaml": "YAML",
    "toml": "TOML",
    "xml": "XML",
    "sql": "SQL",
    "markdown": "Markdown",
    "rst": "reStructuredText",
    "jinja": "Jinja",
    "diff": "Diff",
    "c": "C",
    "cpp": "C++",
    "go": "Go",
    "java": "Java",
    "ruby": "Ruby",
    "perl": "Perl",
    "php": "PHP",
    "awk": "Awk",
    "r": "R",
    "powershell": "PowerShell",
    "docker": "Dockerfile",
    "make": "Makefile",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "objective-c": "Objective-C",
    "objective-c++": "Objective-C++",
    "dart": "Dart",
    "scala": "Scala",
    "groovy": "Groovy",
    "csharp": "C#",
    "elixir": "Elixir",
    "erlang": "Erlang",
    "haskell": "Haskell",
    "ocaml": "OCaml",
    "clojure": "Clojure",
    "elm": "Elm",
    "zig": "Zig",
    "nim": "Nim",
    "julia": "Julia",
    "batch": "Batchfile",
    "scss": "SCSS",
    "sass": "Sass",
    "less": "Less",
    "vue": "Vue",
    "graphql": "GraphQL",
    "terraform": "Terraform",
    "nix": "Nix",
    "protobuf": "Protocol Buffers",
    "cmake": "CMake",
    "vim": "Vim script",
}

_LANGUAGE_COLORS: dict[str, str] = {
    "python": "#3987e5",
    "rust": "#d95926",
    "typescript": "#199e70",
    "tsx": "#199e70",
    "javascript": "#c98500",
    "jsx": "#c98500",
    "lua": "#d55181",
    "sh": "#008300",
    "bash": "#008300",
    "zsh": "#008300",
    "fish": "#008300",
    "css": "#9085e9",
    "scss": "#9085e9",
    "sass": "#9085e9",
    "less": "#9085e9",
    "html": "#e66767",
}

_NEUTRAL_COLOR = "#8a8984"

# Every new slot must be re-validated with the dataviz validator against the
# TUI Statistics surface (#1c1b1a) for lightness, chroma, CVD distance, and
# contrast before landing.


def language_label(language_id: str) -> str:
    """Return the display label for a sase-core language id."""
    if language_id in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[language_id]
    if not language_id:
        return language_id
    return language_id[0].upper() + language_id[1:]


def _language_color(language_id: str | None) -> str:
    """Return the identity color for a language id (neutral fallback)."""
    if language_id is None:
        return UNKNOWN_STYLE
    return _LANGUAGE_COLORS.get(language_id, _NEUTRAL_COLOR)


def language_share_label(part: int | None, whole: int | None) -> str:
    """Format a language share without ever printing a false 100%."""
    if whole is None:
        return DASH
    if not whole:
        return "0%" if part == 0 else DASH
    if part is None:
        return DASH
    if part == 0:
        return "0%"
    percent = round(part * 100 / whole)
    if percent == 0:
        return "<1%"
    if percent == 100 and part < whole:
        return ">99%"
    return f"{percent}%"


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
                    style=_NEUTRAL_COLOR,
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
        color = _language_color(row.language)
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


def top_language(
    languages: tuple[object, ...] | None,
) -> tuple[str, int] | None:
    """Return the (id, lines) of the top lines>0 language, if any."""
    best: tuple[str, int] | None = None
    for item in languages or ():
        name = getattr(item, "name", "")
        lines = getattr(item, "lines", 0) or 0
        if lines <= 0:
            continue
        if best is None or lines > best[1]:
            best = (name, lines)
    return best


def language_cell_text(
    language_id: str | None,
    lines: int | None,
    whole: int | None,
    ctx: RenderContext,
) -> Text:
    """Render the repo LANGUAGE cell (swatch + label + share)."""
    if language_id is None or lines is None or whole is None or not whole:
        return Text(DASH, style=DIM)
    label = language_label(language_id)
    share = language_share_label(lines, whole)
    text = Text()
    if ctx.unicode:
        text.append("● ", style=_language_color(language_id))
    text.append(f"{label} {share}")
    return text


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
        color = _language_color(row.language)
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
    color = _language_color(row.language)
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
    "breakdown_widths",
    "language_cell_text",
    "language_label",
    "language_markdown_rows",
    "language_share_label",
    "make_breakdown_grid",
    "render_language_card_block",
    "render_language_table",
    "top_language",
]
