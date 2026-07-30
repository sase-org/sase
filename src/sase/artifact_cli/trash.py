"""CLI surfaces for listing, purging, and restoring artifact trash."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.config import get_artifact_retention_trash_grace_days
from sase.core.artifact_file_trash import (
    TrashEntry,
    list_trashed_artifact_files,
    purge_trashed_artifact_files,
    restore_trashed_artifact_file,
)


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
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

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
    payload = {
        "schema_version": ARTIFACT_TRASH_SCHEMA_VERSION,
        "purge_all": purge_all,
        "before": cutoff,
        **result.to_json_dict(),
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
    return 0


def _handle_restore(args: argparse.Namespace) -> int:
    reference = str(getattr(args, "reference", "")).strip()
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
