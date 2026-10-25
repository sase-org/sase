"""Markdown language table for the shared Projects report."""

from __future__ import annotations

from sase.stats.project.view import ProjectStatsView
from sase.stats.render._markdown_shared import md_table
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count


def language_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
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
    # Indent child rows like the Rich tree; md_table escapes pipes already.
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
    out_lines = ["## By language", ""] + md_table(headers, indented_rows)
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


__all__ = [
    "language_markdown",
]
