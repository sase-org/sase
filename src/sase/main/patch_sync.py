"""Implementation for ``sase patch sync-*`` commands."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.ace.deltas import refresh_deltas_for_patch
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.main.patch_common import command_prefix
from sase.vcs_provider import VCSProvider


def handle_sync_deltas(
    args: argparse.Namespace,
    *,
    resolve_project_file_fn: Callable[[str | None], str | None],
    refresh_deltas_for_patch_fn: Callable[
        [str, str, str], bool
    ] = refresh_deltas_for_patch,
) -> int:
    """Handle ``sase patch sync-deltas``."""
    project_file = resolve_project_file_fn(args.project_file)
    if not project_file:
        print(
            f"[{command_prefix(args, 'sync-deltas')}] could not infer project file; "
            "pass -p/--project-file or run inside a sase workspace.",
            file=sys.stderr,
        )
        return 1
    if not os.path.isfile(project_file):
        print(
            f"[{command_prefix(args, 'sync-deltas')}] project file not found: "
            f"{project_file}",
            file=sys.stderr,
        )
        return 1

    workspace_dir = args.workspace_dir or os.getcwd()
    ok = refresh_deltas_for_patch_fn(project_file, args.cl_name, workspace_dir)
    if ok:
        print(f"DELTAS refreshed for {args.cl_name} in {project_file}")
        return 0
    print(
        f"[{command_prefix(args, 'sync-deltas')}] failed to refresh DELTAS for "
        f"{args.cl_name}; "
        "DELTAS preserved as-is. See logs for details.",
        file=sys.stderr,
    )
    return 1


def handle_sync_external(
    args: argparse.Namespace,
    *,
    get_vcs_provider_fn: Callable[[str], VCSProvider],
    list_project_records_fn: Callable[..., list[ProjectRecordWire]],
    projects_dir_fn: Callable[[], Path],
    resolve_project_alias_ref_fn: Callable[[str], str],
    select_sync_external_project_fn: Callable[
        [list[ProjectRecordWire], str], ProjectRecordWire | None
    ],
    sync_external_pull_requests_fn: Callable[..., Any],
    console_obj: Any,
) -> int:
    """Handle ``sase patch sync-external``."""
    from rich.table import Table

    records = [
        record
        for record in list_project_records_fn(
            projects_dir_fn(),
            "enabled",
            include_home=False,
            projects_only=True,
        )
        if record.is_project and record.vcs_kind in {"git", "gh"}
    ]
    if args.project:
        selected = select_sync_external_project_fn(
            records,
            resolve_project_alias_ref_fn(str(args.project)),
        )
        if selected is None:
            print(
                f"[{command_prefix(args, 'sync-external')}] project not found: "
                f"{args.project}",
                file=sys.stderr,
            )
            return 1
        records = [selected]

    if args.dry_run:
        console_obj.print(
            "[bold yellow]Dry run:[/bold yellow] no Patches will be written."
        )

    table = Table(title="External PR Mirror")
    table.add_column("Project", style="cyan")
    table.add_column("Fetched", justify="right")
    table.add_column("Filtered", justify="right", style="yellow")
    table.add_column("Adopted", justify="right", style="green")
    table.add_column("Repaired", justify="right", style="green")
    table.add_column("Skipped", justify="right")
    table.add_column("Errors", justify="right", style="red")
    table.add_column("Reason")

    exit_code = 0
    for record in sorted(records, key=lambda item: effective_project_name(item)):
        project_label = effective_project_name(record)
        if not record.workspace_dir:
            table.add_row(
                project_label, "0", "0", "0", "0", "0", "1", "missing_workspace"
            )
            exit_code = 1
            continue
        try:
            provider = get_vcs_provider_fn(record.workspace_dir)
            report = sync_external_pull_requests_fn(
                project_key=record.project_name,
                workspace_dir=record.workspace_dir,
                provider=provider,
                now=datetime.now(UTC),
                dry_run=bool(args.dry_run),
                full=bool(args.full),
            )
        except Exception as exc:  # noqa: BLE001 - CLI reports per-project failures.
            table.add_row(project_label, "0", "0", "0", "0", "0", "1", str(exc))
            exit_code = 1
            continue
        if report.errors:
            exit_code = 1
        table.add_row(
            project_label,
            str(report.fetched),
            str(report.unmirrored),
            str(report.created),
            str(report.repaired),
            str(report.skipped),
            str(report.errors),
            report.reason() or "",
        )

    console_obj.print(table)
    return exit_code


def select_sync_external_project(
    records: list[ProjectRecordWire],
    project_ref: str,
) -> ProjectRecordWire | None:
    folded = project_ref.casefold()
    for record in records:
        if record.project_name == project_ref:
            return record
    for record in records:
        if effective_project_name(record).casefold() == folded:
            return record
        if any(alias.casefold() == folded for alias in record.aliases):
            return record
    return None


__all__ = [
    "handle_sync_deltas",
    "handle_sync_external",
    "select_sync_external_project",
]
