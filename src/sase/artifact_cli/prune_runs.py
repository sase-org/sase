"""Implementation of dry-run-first ``sase artifact prune-runs``."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_retention import (
    ACE_RUN_RETENTION_SCHEMA_VERSION,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.time import get_timezone
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION = ACE_RUN_RETENTION_SCHEMA_VERSION


def handle_prune_runs(args: argparse.Namespace) -> int:
    """Plan ACE-run retention and apply it only when explicitly requested."""

    projects_root = (
        Path(args.projects_root).expanduser()
        if getattr(args, "projects_root", None)
        else None
    )
    projects = load_project_ref_display_snapshot(projects_root=projects_root)
    raw_project = getattr(args, "project", None)
    project = None if raw_project is None else projects.project_key_for_ref(raw_project)
    if raw_project is not None and project is None:
        print(f"Error: unknown project reference: {raw_project}", file=sys.stderr)
        return 2

    months = getattr(args, "keep_recent_months", None)
    policy = AceRunRetentionPolicy(
        now=datetime.now(get_timezone()),
        keep_recent_months=(
            get_artifact_retention_keep_recent_run_months()
            if months is None
            else months
        ),
        project=project,
        limit=None
        if getattr(args, "limit", None) == 0
        else getattr(args, "limit", None),
        projects_root=projects_root,
    )
    protections = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=(
            Path(args.index_path).expanduser()
            if getattr(args, "index_path", None)
            else None
        ),
    )
    plan = plan_ace_run_retention(policy, protections=protections)
    apply = bool(getattr(args, "apply", False))
    blocked = apply and bool(plan.sources_unavailable)
    execution = None
    if apply and not blocked:
        execution = apply_ace_run_retention(
            plan,
            index_path=(
                Path(args.index_path).expanduser()
                if getattr(args, "index_path", None)
                else None
            ),
        )

    payload = {
        "schema_version": ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION,
        "mode": "apply" if apply else "dry_run",
        "blocked": blocked,
        "plan": plan.to_json_dict(),
        "execution": None if execution is None else execution.to_json_dict(),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        console = Console()
        _print_plan(plan, projects=projects, console=console)
        for source in plan.sources_unavailable:
            console.print(f"[yellow]Protection source unavailable:[/yellow] {source}")
        if blocked:
            console.print(
                "[red]Apply refused:[/red] every required protection source "
                "must be readable."
            )
        elif execution is not None:
            console.print(
                f"[green]Removed {execution.removed_runs} run dirs "
                f"({_human_size(execution.bytes_reclaimed)} reclaimed) and "
                f"{execution.removed_empty_shards} empty shards.[/green] "
                f"Artifact-index rows dropped: {execution.deindexed}."
            )
            for message in execution.skipped:
                console.print(f"[yellow]Skipped:[/yellow] {message}")
            for message in execution.errors:
                console.print(f"[red]Error:[/red] {message}")
        else:
            console.print(
                "[cyan]Dry run only; pass --apply to remove selected run dirs "
                "and empty out-of-range shards.[/cyan]"
            )
    return 1 if blocked else 0


def _print_plan(
    plan: AceRunRetentionPlan,
    *,
    projects: ProjectRefDisplaySnapshot,
    console: Console,
) -> None:
    run_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    run_table.add_column("PROJECT")
    run_table.add_column("TIMESTAMP")
    run_table.add_column("SIZE", justify="right")
    run_table.add_column("REASON")
    run_table.add_column("PATH")
    for item in plan.selected:
        run_table.add_row(
            projects.display_snapshot.label_for(item.project),
            item.timestamp,
            _human_size(item.size_bytes),
            item.reason,
            item.artifact_dir,
        )
    if not plan.selected:
        run_table.add_row("[dim]none[/dim]", "-", "-", "-", "-")
    title = (
        f"ACE Run Prune Plan ({plan.counts.selected} run dirs selected, "
        f"{_human_size(plan.reclaimable_bytes)} reclaimable"
        f"{f', {plan.counts.truncated} truncated' if plan.counts.truncated else ''})"
    )
    console.print(Panel(run_table, title=title, border_style="cyan"))

    shard_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    shard_table.add_column("PROJECT")
    shard_table.add_column("KIND")
    shard_table.add_column("PATH")
    for shard in plan.empty_out_of_range_shards:
        shard_table.add_row(
            projects.display_snapshot.label_for(shard.project),
            shard.kind,
            shard.path,
        )
    if not plan.empty_out_of_range_shards:
        shard_table.add_row("[dim]none[/dim]", "-", "-")
    console.print(
        Panel(
            shard_table,
            title=(
                "Empty Out-of-Range Shards "
                f"({plan.counts.empty_out_of_range_shards} selected)"
            ),
            border_style="cyan",
        )
    )


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = ["ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION", "handle_prune_runs"]
