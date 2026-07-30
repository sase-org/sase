"""Implementation of dry-run-first ``sase artifact reclaim``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.core.artifact_file_protection import collect_protected_artifact_ids
from sase.core.artifact_file_reclaim import (
    DEFAULT_RECLAIM_MAX_HISTORY_SCAN,
    ReclaimPlan,
    ReclaimResult,
    execute_artifact_file_reclaim,
    plan_artifact_file_reclaim,
)
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


ARTIFACT_RECLAIM_SCHEMA_VERSION = 1


def handle_reclaim(args: argparse.Namespace) -> int:
    """Plan lossless VCS conversion and apply it only when requested."""

    projects = load_project_ref_display_snapshot()
    raw_project = getattr(args, "project", None)
    project = None if raw_project is None else projects.project_key_for_ref(raw_project)
    if raw_project is not None and project is None:
        print(f"Error: unknown project reference: {raw_project}", file=sys.stderr)
        return 2

    protections = collect_protected_artifact_ids()
    limit = getattr(args, "limit", None)
    plan = plan_artifact_file_reclaim(
        protected_ids=protections.ids,
        max_history_scan=getattr(
            args,
            "max_history_scan",
            DEFAULT_RECLAIM_MAX_HISTORY_SCAN,
        ),
        limit=None if limit == 0 else limit,
        project=project,
    )
    apply = bool(getattr(args, "apply", False))
    blocked = apply and bool(protections.sources_unavailable)
    execution = execute_artifact_file_reclaim(plan) if apply and not blocked else None
    payload = {
        "schema_version": ARTIFACT_RECLAIM_SCHEMA_VERSION,
        "mode": "apply" if apply else "dry_run",
        "blocked": blocked,
        "sources_unavailable": list(protections.sources_unavailable),
        "max_history_scan": getattr(
            args,
            "max_history_scan",
            DEFAULT_RECLAIM_MAX_HISTORY_SCAN,
        ),
        "limit": None if limit == 0 else limit,
        "project": project,
        "plan": plan.to_json_dict(),
        "execution": None if execution is None else execution.to_json_dict(),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_plan(plan, projects=projects)
        for source in protections.sources_unavailable:
            Console().print(f"[yellow]Protection source unavailable:[/yellow] {source}")
        if blocked:
            Console().print(
                "[red]Apply refused:[/red] every required protection source "
                "must be readable."
            )
        elif execution is not None:
            _print_execution(execution)
        else:
            Console().print(
                "[cyan]Dry run only; pass --apply to convert these rows.[/cyan]"
            )
    return 1 if blocked else 0


def _print_plan(
    plan: ReclaimPlan,
    *,
    projects: ProjectRefDisplaySnapshot,
) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("OLD REF", style="bold")
    table.add_column("NEW REF", style="bold")
    table.add_column("LABEL")
    table.add_column("PROJECT")
    table.add_column("DURABLE COMMIT")
    table.add_column("PATH")
    table.add_column("SIZE", justify="right")
    for item in plan.verified:
        table.add_row(
            f"file:{item.old_id}",
            f"file:{item.new_id}",
            item.label,
            projects.display_snapshot.label_for(item.project) if item.project else "-",
            f"{item.vcs_repo}@{item.vcs_sha[:12]}",
            item.vcs_relpath,
            _human_size(item.size_bytes),
        )
    if not plan.verified:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-", "-", "-")
    suffix = f", {plan.truncated} truncated" if plan.truncated else ""
    Console().print(
        Panel(
            table,
            title=(
                f"Artifact Reclaim Plan ({len(plan.verified)} verified, "
                f"{_human_size(plan.reclaimable_bytes)} recoverable{suffix})"
            ),
            border_style="cyan",
        )
    )

    unresolved = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
    )
    unresolved.add_column("UNRESOLVED REASON")
    unresolved.add_column("ROWS", justify="right")
    for reason, count in plan.unresolved_counts.items():
        unresolved.add_row(reason.replace("_", " "), str(count))
    if not plan.unresolved_counts:
        unresolved.add_row("[dim]none[/dim]", "0")
    Console().print(
        Panel(unresolved, title="Rows Left Untouched", border_style="yellow")
    )


def _print_execution(result: ReclaimResult) -> None:
    console = Console()
    for item in result.reclaimed:
        console.print(
            f"[green]Reclaimed[/green] file:{item.old_id} -> file:{item.new_id}"
        )
    console.print(
        f"[green]Converted {result.rows_reclaimed} rows "
        f"({_human_size(result.bytes_moved_to_trash)} moved to trash).[/green] "
        f"Trash: {result.trash_root or '-'}"
    )
    console.print(
        "[yellow]Disk space is freed only after the corresponding trash "
        "entries are purged.[/yellow]"
    )


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = ["ARTIFACT_RECLAIM_SCHEMA_VERSION", "handle_reclaim"]
