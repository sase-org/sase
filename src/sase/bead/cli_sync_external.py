"""``sase bead sync-external`` — the manual external issue mirror entry point.

Runs the exact same reconciliation pass as the ``external_issue_mirror`` AXE
chop (:func:`sase.external_mirror.issues.run_issue_mirror_for_project`), so a
project owner can trigger or preview a pass without waiting for the next
scheduled tick.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.markup import escape

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.external_mirror.issues import MirrorReport, run_issue_mirror_for_project


def handle_bead_sync_external(args: argparse.Namespace) -> None:
    """Run one external issue mirror pass for one or every enabled project."""
    project_arg = getattr(args, "project", None)
    dry_run = bool(getattr(args, "dry_run", False))
    full = bool(getattr(args, "full", False))

    records = _resolve_project_records(project_arg)
    console = Console()
    reports: list[MirrorReport] = []
    for record in records:
        workspace_dir = record.workspace_dir or ""
        display_name = effective_project_name(record)
        if not workspace_dir:
            reports.append(
                MirrorReport(
                    project=record.project_name,
                    display_name=display_name,
                    degraded="no_workspace",
                )
            )
            continue
        reports.append(
            run_issue_mirror_for_project(
                project_key=record.project_name,
                display_name=display_name,
                workspace_dir=workspace_dir,
                dry_run=dry_run,
                full=full,
                source="cli",
            )
        )

    _render_reports(console, reports, dry_run=dry_run)

    if reports and all(report.degraded for report in reports):
        sys.exit(1)


def _resolve_project_records(project_arg: str | None) -> list[ProjectRecordWire]:
    if project_arg is None:
        return [
            record
            for record in list_project_records(
                sase_projects_dir(),
                "enabled",
                include_home=False,
                projects_only=True,
            )
            if record.is_project
        ]

    folded = project_arg.casefold()
    records = list_project_records(
        sase_projects_dir(), "all", include_home=False, projects_only=True
    )
    for record in records:
        if not record.is_project:
            continue
        candidates = {
            record.project_name.casefold(),
            effective_project_name(record).casefold(),
            *(alias.casefold() for alias in record.aliases),
        }
        if folded in candidates:
            return [record]
    print(f"Error: project {project_arg!r} was not found", file=sys.stderr)
    sys.exit(1)


def _render_reports(
    console: Console,
    reports: list[MirrorReport],
    *,
    dry_run: bool,
) -> None:
    if not reports:
        console.print("No enabled projects to mirror.")
        return
    for report in reports:
        line = (
            f"[bold]{escape(report.display_name)}[/bold]  "
            f"issues={report.issues_seen} created={report.beads_created} "
            f"notes={report.notes_appended} deferred={report.deferred}"
        )
        if report.beads_closed:
            line += f" closed={report.beads_closed}"
        if report.beads_reopened:
            line += f" reopened={report.beads_reopened}"
        if report.unmirrored:
            line += f" filtered={report.unmirrored}"
        if report.degraded:
            line += f"  [yellow]degraded={escape(report.degraded)}[/yellow]"
        console.print(line)
        if dry_run:
            for ref in report.created_refs:
                console.print(f"  [green]would create[/green] {escape(ref)}")
            for ref in report.closed_refs:
                console.print(f"  [yellow]would close[/yellow] {escape(ref)}")
            for ref in report.reopened_refs:
                console.print(f"  [green]would reopen[/green] {escape(ref)}")


__all__ = ["handle_bead_sync_external"]
