"""CLI surfaces for listing, purging, and restoring artifact trash."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.config import get_artifact_retention_trash_grace_days
from sase.core.agent_artifact_run_retention import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_trash import (
    AceRunTrashBatch,
    AceRunTrashListResult,
    AceRunTrashPurgeResult,
    AceRunTrashRestoreResult,
    list_ace_run_trash,
    purge_ace_run_trash,
    restore_ace_run_trash,
)
from sase.core.artifact_file_trash import (
    TrashEntry,
    list_trashed_artifact_files,
    purge_trashed_artifact_files,
    restore_trashed_artifact_file,
)
from sase.project_display_names import load_project_ref_display_snapshot


ARTIFACT_TRASH_SCHEMA_VERSION = 1


def handle_trash(args: argparse.Namespace) -> int:
    """Dispatch a parsed artifact-trash subcommand."""

    handlers = {
        "list": _handle_list,
        "purge": _handle_purge,
        "restore": _handle_restore,
    }
    subcommand = getattr(args, "trash_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print(
            "Usage: sase artifact trash {list,purge,restore}",
            file=sys.stderr,
        )
        return 2
    return handler(args)


def _handle_list(args: argparse.Namespace) -> int:
    result = list_trashed_artifact_files()
    limit = getattr(args, "limit", 50)
    entries = result.entries if limit == 0 else result.entries[:limit]
    now = datetime.now(UTC)
    grace_days = get_artifact_retention_trash_grace_days()
    run_trash = list_ace_run_trash()
    payload = {
        "schema_version": ARTIFACT_TRASH_SCHEMA_VERSION,
        "entries": [
            {
                **entry.to_json_dict(),
                "past_grace_period": _past_grace_period(
                    entry,
                    now=now,
                    grace_days=grace_days,
                ),
            }
            for entry in entries
        ],
        "unreadable_entries": result.unreadable_entries,
        "truncated": max(0, len(result.entries) - len(entries)),
        "run_batches": [batch.to_json_dict() for batch in run_trash.batches],
        "unreadable_run_journals": run_trash.unreadable_journal_count,
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_run_trash_panel(run_trash, grace_days=grace_days)

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ENTRY ID", style="bold")
    table.add_column("ARTIFACT REF")
    table.add_column("LABEL")
    table.add_column("SIZE", justify="right")
    table.add_column("TRASHED AT")
    table.add_column("PAST GRACE")
    for entry in entries:
        table.add_row(
            entry.entry_id,
            f"file:{entry.artifact_id}",
            entry.record.label,
            _human_size(entry.size_bytes),
            entry.trashed_at,
            "yes"
            if _past_grace_period(entry, now=now, grace_days=grace_days)
            else "no",
        )
    if not entries:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-", "-")
    title = f"Artifact Trash ({len(entries)} entries)"
    if len(result.entries) > len(entries):
        title += f", {len(result.entries) - len(entries)} truncated"
    Console().print(Panel(table, title=title, border_style="cyan"))
    if result.unreadable_entries:
        Console().print(
            f"[yellow]Unreadable trash entries: {result.unreadable_entries}[/yellow]"
        )
    return 0


def _handle_purge(args: argparse.Namespace) -> int:
    purge_all = bool(getattr(args, "all", False))
    cutoff = (
        datetime.now(UTC) - timedelta(days=get_artifact_retention_trash_grace_days())
    ).isoformat()
    result = purge_trashed_artifact_files(
        before=cutoff,
        purge_all=purge_all,
    )
    raw_projects_root: object = getattr(args, "projects_root", None)
    projects_root = (
        Path(str(raw_projects_root)).expanduser() if raw_projects_root else None
    )
    protections = collect_ace_run_retention_protections(projects_root=projects_root)
    run_result: AceRunTrashPurgeResult = purge_ace_run_trash(
        protections,
        purge_all=purge_all,
        projects_root=projects_root,
    )
    payload = {
        "schema_version": ARTIFACT_TRASH_SCHEMA_VERSION,
        "purge_all": purge_all,
        "before": cutoff,
        **result.to_json_dict(),
        "run_batches": run_result.to_json_dict(),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        Console().print(
            f"[green]Purged {len(result.purged_entry_ids)} trash entries "
            f"({_human_size(result.freed_bytes)} freed).[/green]"
        )
        if result.unreadable_entries:
            Console().print(
                f"[yellow]Unreadable trash entries skipped: "
                f"{result.unreadable_entries}[/yellow]"
            )
        if run_result.blocked_reason is not None:
            Console().print(
                f"[red]ACE run trash purge blocked "
                f"({run_result.blocked_reason}):[/red] nothing purged; "
                "collect protections with "
                "`sase artifact prune-runs` and retry."
            )
        else:
            Console().print(
                f"[green]Purged {run_result.purged} ACE run batches "
                f"({_human_size(run_result.freed_bytes)} freed); "
                f"{run_result.restored} run(s) restored as newly protected."
                "[/green]"
            )
            if run_result.reindexed:
                Console().print(
                    f"[green]Re-indexed {run_result.reindexed} restored run(s).[/green]"
                )
        for message in run_result.index_errors:
            Console().print(f"[yellow]Index:[/yellow] {message}")
    if run_result.blocked_reason is not None:
        return 1
    return 0


def _handle_restore(args: argparse.Namespace) -> int:
    reference = str(getattr(args, "reference", "")).strip()
    if reference.startswith("runs:"):
        return _handle_restore_run_batch(args, reference.removeprefix("runs:"))
    listing = list_trashed_artifact_files()
    normalized = reference.removeprefix("file:")
    entry = next(
        (
            candidate
            for candidate in listing.entries
            if candidate.entry_id == reference or candidate.artifact_id == normalized
        ),
        None,
    )
    if entry is None:
        print(
            f"Error: trash entry or artifact reference not found: {reference}",
            file=sys.stderr,
        )
        return 1
    result = restore_trashed_artifact_file(entry.entry_id)
    if bool(getattr(args, "json", False)):
        json.dump(
            {
                "schema_version": ARTIFACT_TRASH_SCHEMA_VERSION,
                **result.to_json_dict(),
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        Console().print(
            f"[green]Restored {result.artifact_id}.[/green]\n"
            f"Payload: {result.restored_path or '(byte-free row)'}\n"
            f"Index: {result.index_path}"
        )
    return 0


def _is_safe_batch_id(value: str) -> bool:
    def _ok(char: str) -> bool:
        return ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9")

    return (
        0 < len(value) <= 128
        and _ok(value[0])
        and all(_ok(char) or char in "-_" for char in value)
    )


def _handle_restore_run_batch(args: argparse.Namespace, batch_id: str) -> int:
    batch_id = batch_id.strip()
    if not batch_id:
        print("Error: trash restore needs a batch id: runs:<batch_id>", file=sys.stderr)
        return 2
    if not _is_safe_batch_id(batch_id):
        print(
            f"Error: invalid run-trash batch id: {batch_id!r} "
            "(letters, digits, '-' and '_' only)",
            file=sys.stderr,
        )
        return 2
    raw_projects_root: object = getattr(args, "projects_root", None)
    projects_root = (
        Path(str(raw_projects_root)).expanduser() if raw_projects_root else None
    )
    result: AceRunTrashRestoreResult = restore_ace_run_trash(
        batch_id, projects_root=projects_root
    )
    payload = {
        "schema_version": ARTIFACT_TRASH_SCHEMA_VERSION,
        **result.to_json_dict(),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        Console().print(
            f"[green]Restored {result.restored} run(s) from batch {batch_id}; "
            f"{result.conflicts} conflict(s) stayed in trash.[/green]"
        )
        if result.reindexed:
            Console().print(
                f"[green]Re-indexed {result.reindexed} restored run(s).[/green]"
            )
        for message in result.index_errors:
            Console().print(f"[yellow]Index:[/yellow] {message}")
    if result.blocked_reason is not None or result.errors > 0:
        return 1
    return 0


def _print_run_trash_panel(
    run_trash: AceRunTrashListResult,
    *,
    grace_days: int,
) -> None:
    projects = load_project_ref_display_snapshot()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("BATCH", style="bold")
    table.add_column("CREATED")
    table.add_column("RUNS", justify="right")
    table.add_column("SIZE", justify="right")
    table.add_column("PROJECTS")
    table.add_column("RESTORABLE UNTIL")
    table.add_column("STATUS")
    for batch in run_trash.batches:
        labels = ", ".join(
            projects.display_snapshot.label_for(key) for key in batch.projects[:4]
        )
        if len(batch.projects) > 4:
            labels += f" +{len(batch.projects) - 4} more"
        table.add_row(
            batch.id,
            batch.created_at,
            f"{batch.run_count:,}",
            _human_size(batch.bytes),
            labels or "-",
            _restorable_until(batch, grace_days=grace_days),
            batch.status,
        )
    if not run_trash.batches:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-", "-", "-")
    Console().print(
        Panel(
            table,
            title=f"ACE Run Trash ({len(run_trash.batches)} batches)",
            border_style="cyan",
        )
    )
    if run_trash.unreadable_journal_count:
        Console().print(
            "[yellow]Unreadable run-trash journals: "
            f"{run_trash.unreadable_journal_count}[/yellow]"
        )


def _restorable_until(batch: AceRunTrashBatch, *, grace_days: int) -> str:
    try:
        created = datetime.fromisoformat(batch.created_at.replace("Z", "+00:00"))
    except ValueError:
        return "-"
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (created + timedelta(days=grace_days)).date().isoformat()


def _past_grace_period(
    entry: TrashEntry,
    *,
    now: datetime,
    grace_days: int,
) -> bool:
    try:
        trashed_at = datetime.fromisoformat(entry.trashed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return trashed_at <= now - timedelta(days=grace_days)


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = ["ARTIFACT_TRASH_SCHEMA_VERSION", "handle_trash"]
