"""Human and JSON rendering helpers for shared diagnostics."""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.diagnostics.models import (
    CheckStatus,
    DiagnosticCheck,
    DiagnosticReport,
    diagnostic_report_to_dict,
    redact_string,
)
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    humanize_cl_names_in_text,
)

_STATUS_STYLES: dict[CheckStatus, str] = {
    "OK": "green",
    "WARN": "yellow",
    "ERROR": "red",
    "SKIP": "dim",
}


def diagnostic_report_to_json(report: DiagnosticReport, *, indent: int = 2) -> str:
    """Serialize a report to redacted JSON without Rich markup."""
    return json.dumps(diagnostic_report_to_dict(report), indent=indent, sort_keys=True)


def render_diagnostic_report(
    report: DiagnosticReport,
    *,
    verbose: bool = False,
    console: Console | None = None,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
) -> None:
    """Render a compact grouped Rich report."""
    target = console or Console()
    renderables: list[RenderableType] = [
        _summary_panel(
            report,
            verbose=verbose,
            project_display_snapshot=project_display_snapshot,
        )
    ]
    grouped = _group_checks(_visible_checks(tuple(report.checks), verbose=verbose))
    if grouped:
        for group, checks in grouped.items():
            renderables.append(
                _checks_table(
                    group,
                    checks,
                    verbose=verbose,
                    project_display_snapshot=project_display_snapshot,
                )
            )
    else:
        renderables.append(
            Panel(
                Text("No diagnostic checks were selected.", style="dim"),
                title="Checks",
                border_style="cyan",
            )
        )
    renderables.append(_counts_panel(report))
    target.print(Group(*renderables))


def _summary_panel(
    report: DiagnosticReport,
    *,
    verbose: bool,
    project_display_snapshot: ProjectDisplaySnapshot | None,
) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")
    table.add_row("Status", _status_text(report.status))
    project = report.project or "-"
    if report.project and project_display_snapshot is not None:
        project = project_display_snapshot.label_for(report.project)
    table.add_row("Project", Text(project, overflow="fold"))
    if verbose:
        table.add_row("Generated", Text(report.generated_at, overflow="fold"))
        table.add_row("CWD", Text(redact_string(report.cwd), overflow="fold"))
        table.add_row(
            "SASE home", Text(redact_string(report.sase_home), overflow="fold")
        )
        table.add_row("Deep", "yes" if report.deep else "no")
        table.add_row("Strict", "yes" if report.strict else "no")
    table.add_row("Checks", str(len(report.checks)))
    return Panel(table, title=f"SASE Doctor {report.status}", border_style="cyan")


def _counts_panel(report: DiagnosticReport) -> Panel:
    counts = report.counts
    summary = ", ".join(f"{status}: {counts[status]}" for status in counts)
    return Panel(Text(f"Summary: {summary}"), border_style="cyan")


def _checks_table(
    group: str,
    checks: Sequence[DiagnosticCheck],
    *,
    verbose: bool,
    project_display_snapshot: ProjectDisplaySnapshot | None,
) -> Table:
    table = Table(title=_group_title(group), show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Summary", overflow="fold")
    table.add_column("Next Step", overflow="fold")
    if verbose:
        table.add_column("Details", overflow="fold")
        table.add_column("ms", justify="right", no_wrap=True)

    for check in checks:
        summary = check.summary
        if check.id == "project.current" and project_display_snapshot is not None:
            # ``project.current`` embeds the canonical project key in its
            # otherwise human-facing summary.  Its data and next-step command
            # arguments intentionally remain exact/canonical.
            summary = humanize_cl_names_in_text(
                summary,
                snapshot=project_display_snapshot,
            )
        row: list[RenderableType] = [
            _status_text(check.status),
            Text(check.id, overflow="fold"),
            Text(redact_string(summary), overflow="fold"),
            Text(_join_lines(check.next_steps), overflow="fold"),
        ]
        if verbose:
            row.extend(
                [
                    Text(_join_lines(check.details), overflow="fold"),
                    Text(str(check.duration_ms)),
                ]
            )
        table.add_row(*row)
    return table


def _visible_checks(
    checks: Sequence[DiagnosticCheck],
    *,
    verbose: bool,
) -> tuple[DiagnosticCheck, ...]:
    if verbose:
        return tuple(checks)

    visible: list[DiagnosticCheck] = []
    groups_with_ok: set[str] = set()
    for check in checks:
        if check.status != "OK":
            visible.append(check)
            continue
        if check.group not in groups_with_ok:
            visible.append(check)
            groups_with_ok.add(check.group)
    return tuple(visible)


def _group_checks(
    checks: Sequence[DiagnosticCheck],
) -> OrderedDict[str, tuple[DiagnosticCheck, ...]]:
    grouped: OrderedDict[str, list[DiagnosticCheck]] = OrderedDict()
    for check in checks:
        grouped.setdefault(check.group, []).append(check)
    return OrderedDict((group, tuple(items)) for group, items in grouped.items())


def _status_text(status: CheckStatus) -> Text:
    return Text(status, style=_STATUS_STYLES[status])


def _group_title(group: str) -> str:
    return group.replace("_", " ").replace(".", " ").title()


def _join_lines(lines: Sequence[str]) -> str:
    if not lines:
        return "-"
    return "\n".join(redact_string(line) for line in lines)
